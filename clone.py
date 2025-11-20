import os
import subprocess
import json
import requests
import re

import logging

from time import strftime
from pathlib import Path
import json

import pprint

log_format : str = '%(asctime)s:%(levelname)s:%(name)s: %(message)s'
logger : logging.Logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format=log_format)

organisation : str = "spraakbanken"
token : str = os.environ["GITHUB_TOKEN"]
data_dir : str = "/tmp/github"

default_headers = {"Accept": "application/vnd.github+json",  "Authorization": "Bearer {}".format(token), "X-GitHub-Api-Version": "2022-11-28"}

def get_paginated(url : str, headers: dict) -> list[requests.Response]:
    """Loads data from the Github API, accessing all the pages"""
    logger.info("Load %s", url)
    responses : list[requests.Response] = []
    link_regex : re.Pattern = re.compile('<(https://.*?)>; rel="next"')
    response : requests.Response = requests.get(url, headers=default_headers)
    responses.append(response)
    if 'link' in response.headers:
        urls : list[str] = response.headers['Link'].split(', ')
        for url in urls:
            match = link_regex.match(url)
            if match:
                next_url : str = match.group(1)
                logger.info("Load %s", next_url)
                response : requests.Response = requests.get(next_url, headers=headers)
                responses.append(response)
                urls += response.headers['Link'].split(', ')
    return responses

def clone_repo(src : str ,dest : Path, git_parameters : list[str] = ["--mirror"], ssh_command : str = "ssh -o User=git") -> None:
    """Clones a git repository with optional list of parameter, default --mirror"""
    git_command : list[str] = ["git", "clone"] + git_parameters + [src, dest.as_posix()]
    logger.info("Clone %s into %s", src, dest)
    logger.info(' '.join(git_command))
    result = subprocess.run(' '.join(git_command), shell=True,env={'GIT_SSH_COMMAND': ssh_command})
    pprint.pp(result)

def flatten(in_list : list) -> list:
    out_list : list = []
    for element in in_list:
        if isinstance(element,list):
            out_list += element
        else:
            out_list.append(element)
    return out_list

if __name__ == '__main__':
    # 0. start
    logger.info("Start cloning %s", organisation)

    # 1. create output directory
    data_path : Path = Path(data_dir) / organisation / strftime("%Y%m%d-%H%M")
    data_path.mkdir(mode=0o755, parents=True, exist_ok=True)

    # 2. Clone repositories and issues
    # 2.1. List all repositories
    
    # repositories : list[requests.Response] = get_paginated("https://api.github.com/orgs/{}/repos".format(organisation),default_headers)
    # repository_list : list[dict] = [{'name': repo['name'], 'url': repo['git_url'], 'has_issues': repo['has_issues'], 'has_wiki': repo['has_wiki'], 'json': repo} for response in repositories for repo in response.json() ]
    repositories : list[requests.Response] = get_paginated("https://api.github.com/repos/spraakbanken/clone-test", default_headers)
    repository_list : list[dict] = [{'name': repo['name'], 'url': repo['git_url'], 'has_issues': repo['has_issues'], 'has_wiki': repo['has_wiki'], 'json': repo} for response in repositories for repo in [response.json()] ] 

    
    # 2.2. Clone repositories and dump issues
    for repository in repository_list:
        # 2.2.1 Store repository infos
        with open(data_path / (repository['name'] + ".json"), "w") as f:
            json.dump(repository['json'], f, indent="\t")
        # # 2.2.2 Clone repositories
        # clone_path : Path = data_path / repository['name']
        # clone_repo("ssh+" + repository['url'], clone_path)
        # # 2.2.3 Clone wikis
        # if repository['has_wiki']:
        #     wiki_url = "ssh+" + repository['url'].replace('.git','.wiki.git')
        #     wiki_clone_path : Path = data_path / (repository['name'] + ".wiki")
        #     clone_repo(wiki_url,wiki_clone_path)
        # 2.2.4 Dump issues
        if repository['has_issues']:
            logger.info("Dump issues for %s", repository['name'])
            # List all issues (both open and closed)
            issues : list[requests.Response] = get_paginated("https://api.github.com/repos/{}/{}/issues?state=all".format(organisation, repository['name']), default_headers)
            issue_list : list[dict] = []
            for issue in flatten([issue.json() for issue in issues]):
                issue_number : int = issue['number']
                # Get timeline
                logger.info("Dump timeline for issue %d of %s", issue_number, repository['name'])
                timeline : list[requests.Response] = get_paginated("https://api.github.com/repos/{}/{}/issues/{}/timeline".format(organisation, repository['name'],issue_number), default_headers)
                # get comments
                logger.info("Dump comments for issue %d of %s", issue_number, repository['name'])
                comments : list[requests.Response] = get_paginated("https://api.github.com/repos/{}/{}/issues/{}/comments".format(organisation, repository['name'],issue_number), default_headers)
                comment_list : list[dict] = flatten([comment.json() for comment in comments])
                file_link_regex : re.Pattern = re.compile('\\((https://github.com/user-attachments/files/\\d+/([^)]+))\\)')
                # get attachments
                attachment_list : list[dict] = []
                for comment in comment_list:
                    link_match = file_link_regex.search(comment["body"])
                    if link_match:
                        logger.info("Found attached file %s at %s", link_match.group(2), link_match.group(1))
                        attachment_list.append({'url': link_match.group(1), 'file': link_match.group(2)})
                if attachment_list:
                    file_download_path = data_path / "attachments" / repository['name']
                    file_download_path.mkdir(mode=0o755, parents=True, exist_ok=True)
                    for attachment in attachment_list:
                        logger.info("Download file %s to %s", attachment['url'], attachment['file'])
                        result = requests.get(attachment['url'], default_headers)
                        pprint.pp(result)
                issue_list.append({'issue': issue, 'timeline': flatten([event.json() for event in timeline])})
            with open(data_path / (repository['name'] + "_issues.json"), "w") as f:
                json.dump(issue_list, f, indent="\t")
    # 3. Clone projects
    # get releases?
    logger.info("Done")
