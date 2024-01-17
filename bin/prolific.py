#!/usr/bin/env python3
import sys
import os

import requests
import re

class Prolific(object):
    """Prolific API wrapper"""
    def __init__(self, token=None):
        super(Prolific, self).__init__()
        if token is None:
            token = os.getenv('PROLIFIC_TOKEN')
            if not token:
                raise ValueError('You must provide a token or set the PROLIFIC_TOKEN environment variable.')

        self.token = token

    def request(self, method, url, **kws):
        if url.startswith('/'):
            url = 'https://api.prolific.co/api/v1' + url
        if not url.endswith('/'):
            url += '/'
        r = requests.request(method, url, **kws, headers={
            'Authorization': f'Token {self.token}',
        })
        response = r.json()
        if r.ok:
            return response
        else:
            print(f'Bad request! {url}')
            print(response)

    def get(self, url, **kws):
        return self.request('GET', url, **kws)

    def post(self, url, json=None, **kws):
        return self.request('POST', url, json=json, **kws)

    def patch(self, url, json=None, **kws):
        return self.request('PATCH', url, json=json, **kws)

    def post_duplicate(self, study_id, **kws):
        # name, internal_name, description, total_available_places

        new = self.post(f'/studies/{study_id}/clone/')
        new_id = new['id']
        if 'name' not in kws:
            kws['name'] = new['name'].replace(' Copy', '')

        new = self.patch(f'/studies/{new_id}/', kws)

        new['cost'] = f"${new['total_cost'] / 100:.2f}"

        for k in ['name', 'internal_name', 'description', 'total_available_places', 'cost']:
            print(k + ': ' + str(new[k]))
        y = input(f'Go ahead? [y/N] ')
        if y in 'yY':
            self.post(f'/studies/{new_id}/transition/', {
                "action": "PUBLISH"
            })
            print('Posted! See submssisions at:')
            print(f'https://app.prolific.co/researcher/workspaces/studies/{new_id}/submissions')
        else:
            print('NOT posting')

    def last_study(self, project_id):
        return self.get(f'/projects/{project_id}/studies/')['results'][-1]['id']

    def approve_all(self, study_id, ignore_code=False):
        to_approve = []
        bad_code = []
        submissions = self.get(f'/studies/{study_id}/submissions')['results']
        completion_code = self.get(f'/studies/{study_id}/')['completion_code']

        for sub in submissions:
            if sub['status'] != 'AWAITING REVIEW':
                continue
            if ignore_code or sub['study_code'] == completion_code:
                to_approve.append(sub["participant_id"])
            else:
                bad_code.append(sub["participant_id"])

        if bad_code:
            print(f'{len(bad_code)} submissions have an incorrect code. Check',
                f"https://app.prolific.co/researcher/workspaces/studies/{study_id}/submissions")

        if to_approve:
            self.post("/submissions/bulk-approve/", {
                "study_id": study_id,
                "participant_ids": to_approve
            })
            print(f'Approved {len(to_approve)} submissions')
        else:
            print('All submissions have already been approved')


    def assign_bonuses(self, study_id, bonuses):
        submissions = self.get(f'/studies/{study_id}/submissions')['results']
        previous_bonus = {sub['participant_id']: sum(sub['bonus_payments']) / 100 for sub in submissions}

        # n_bonused = sum(previous_bonus > 0)
        # if n_bonused:
        #     print(f'{n_bonused} participants already have bonuses, {len(bonuses) - n_bonused} to be bonused')
        participants = previous_bonus.keys()
        missing = set(bonuses.keys()) - set(participants)
        if missing:
            print('WARNING: some entries of bonuses.csv do not have submissions. Skipping these.')
            for m in missing:
                print('  ', m)

        new_bonus = {
            p: bonuses.get(p, 0) - previous_bonus[p] for p in participants
        }
        bonus_string = '\n'.join(f'{p},{bonuses:.2f}' for p, bonuses in new_bonus.items() if bonuses > 0)

        if not bonus_string:
            print('No bonuses due')
        else:
            resp = self.post('/submissions/bonus-payments/', {
                'study_id': study_id,
                'csv_bonuses': bonus_string
            })

            amt = resp['total_amount'] / 100
            yes = input(f'Pay ${amt:.2f} in bonuses? [N/y]: ')
            if yes == 'y':
                self.post(f'/bulk-bonus-payments/{resp["id"]}/pay/')
                print('Bonuses paid')
            else:
                print('NOT paying bonuses')


def get_project_id():
    if os.path.isfile('.project_id'):
        with open('.project_id') as f:
            return f.read()
    else:
        print(
            "Please enter your prolific project id.\n"
            "You can find this in the URL when you select your project on the the prolific website, e.g\n"
            "https://app.prolific.co/researcher/workspaces/projects/644364ccfceb189178b7187c\n"
            "You can also enter the whole URL"
        )
        project_id = input("project id: ")
        if 'projects/' in project_id:
            project_id = project_id.split('projects/')[1].strip()

        with open('.project_id', 'w') as f:
            f.write(project_id)
            print("Saved to .project_id - we won't ask again.")
        return project_id


def generate_internal_name():
    import configparser
    c = configparser.ConfigParser()
    c.read('config.txt')
    version = c["Task Parameters"]["experiment_code_version"]
    project_name = c["Server Parameters"]["adserver_revproxy_host"].split('.')[0]
    return '-'.join([project_name, version])


def main():
    token = os.getenv('PROLIFIC_TOKEN')
    if not token:
        print('You must set the PROLIFIC_TOKEN environment variable to use this script.')
        exit(1)

    project_id = get_project_id()
    prolific = Prolific(token)

    cmd = sys.argv[1]

    if cmd == 'approve_and_bonus':
        # NOTE: we're currently assuming you want to approve and bonus the last study
        # you ran. This could easily be generalized of course.
        study_id = prolific.last_study(project_id)
        prolific.approve_all(study_id)

        import pandas as pd
        bonuses = dict(pd.read_csv('bonus.csv', header=None).set_index(0)[1])
        prolific.assign_bonuses(study_id, bonuses)

    elif cmd == 'post_duplicate':
        study_id = prolific.last_study(project_id)
        prolific.post_duplicate(study_id, internal_name=generate_internal_name(), total_available_places=3)


if __name__ == '__main__':
    main()