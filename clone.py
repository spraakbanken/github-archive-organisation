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

def get_paginated(url : str, headers: dict) -> (list[requests.Response],list[dict]):
    """Loads data from the Github API, accessing all the pages. Returns both the list of Response objects and the flattened list of JSON bodies"""
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
    return (responses,flatten([r.json() for r in responses]))

def clone_repo(src : str ,dest : Path, git_parameters : list[str] = ["--mirror"], ssh_command : str = "ssh -o User=git") -> None:
    """Clones or fetch a git repository with optional list of parameter, default --mirror"""
    if dest.exists():
        git_command : list[str] = ["git", "fetch"]
        logger.info("Fetch into %s", dest)
        working_dir = dest
    else:
        git_command : list[str] = ["git", "clone"] + git_parameters + [src, dest.as_posix()]
        logger.info("Clone %s into %s", src, dest)
        working_dir = None
    logger.info(' '.join(git_command))
    result = subprocess.run(' '.join(git_command), shell=True,env={'GIT_SSH_COMMAND': ssh_command}, cwd=working_dir)
    return result

def flatten(in_list : list) -> list:
    """Flatten a list of lists"""
    out_list : list = []
    for element in in_list:
        if isinstance(element,list):
            out_list += element
        else:
            out_list.append(element)
    return out_list

def try_download(url : str, outfile : str) -> None:
    """Try to download a file from an url and keep track of the failures"""
    logger.info("Try to download file %s to %s", url, outfile)
    result : requests.Result = requests.get(url, headers=default_headers, stream=True)
    if result.status_code == 200:
        with open(outfile, "wb") as f:
            f.write(result.raw.data)
        return True
    else:
        return False

if __name__ == '__main__':
    # 0. start
    logger.info("Start cloning %s", organisation)

    # 1. create output directory
    data_path : Path = Path(data_dir) / organisation / strftime("%Y%m%d-%H%M")
    data_path.mkdir(mode=0o755, parents=True, exist_ok=True)

    # 2. Clone repositories and archive organisation
    # 2.1. List all repositories
    
    _,repositories = get_paginated("https://api.github.com/orgs/{}/repos".format(organisation),headers=default_headers)
    repository_list : list[dict] = [{'name': repo['name'], 'url': repo['git_url'], 'has_issues': repo['has_issues'], 'has_wiki': repo['has_wiki'], 'json': repo} for repo in repositories]
    
    # 2.2. Clone repositories archive organisation
    for repository in repository_list:
        archive_path = data_path / "archive" / repository['name']
        archive_path.mkdir(mode=0o755, parents=True, exist_ok=True)
        # 2.2.1 Archive repository infos
        with open(archive_path / "repository.json", "w") as f:
            json.dump(repository['json'], f, indent="\t")
        # 2.2.2 Clone repositories
        clone_path : Path = data_path / repository['name']
        clone_repo("ssh+" + repository['url'], clone_path)
        # 2.2.3 Clone wikis
        if repository['has_wiki']:
            wiki_url = "ssh+" + repository['url'].replace('.git','.wiki.git')
            wiki_clone_path : Path = data_path / (repository['name'] + ".wiki")
            clone_repo(wiki_url,wiki_clone_path)
        # 2.2.4 Archive issues
        if repository['has_issues']:
            logger.info("Archive issues for %s", repository['name'])
            # List all issues (both open and closed)
            _,issues = get_paginated("https://api.github.com/repos/{}/{}/issues?state=all".format(organisation, repository['name']), headers=default_headers)
            issue_list : list[dict] = []
            for issue in issues:
                issue_number : int = issue['number']
                # Get timeline
                logger.info("Dump timeline for issue %d of %s", issue_number, repository['name'])
                _,timeline = get_paginated("https://api.github.com/repos/{}/{}/issues/{}/timeline".format(organisation, repository['name'],issue_number), headers=default_headers)
                # get comments
                logger.info("Dump comments for issue %d of %s", issue_number, repository['name'])
                _,comments = get_paginated("https://api.github.com/repos/{}/{}/issues/{}/comments".format(organisation, repository['name'],issue_number), headers=default_headers)
                file_link_regex : re.Pattern = re.compile('\\((https://github.com/user-attachments/files/\\d+/([^)]+))\\)')
                # get attachments
                attachment_path = archive_path / "attachments"
                attachment_path.mkdir(mode=0o755, parents=True, exist_ok=True)
                failed_downloads: list[dict] = []
                for comment in comments:
                    link_match = file_link_regex.search(comment["body"])
                    if link_match:
                        attached_file_url = link_match.group(1)
                        attached_file_name = link_match.group(2)
                        # Make sure that the download folder exists
                        attachment_path.mkdir(parents=True, exist_ok=True)
                        logger.info("Found attached file %s at %s", attached_file_name, attached_file_url)
                        # Try to download
                        if not try_download(attached_file_url,attachment_path / attached_file_name):
                            failed_downloads.append({'url': attached_file_url, 'file': attached_file_name})
                            
                # Write failed downloads to file
                if failed_downloads:
                    with open(attachment_path / "missing_downloads.json", "w") as f:
                        json.dump(failed_downloads, f, indent="\t")
                # Add issue to list
                issue |= {'timeline': timeline}
                issue_list.append(issue)
            # Write issues to file
            with open(archive_path / "issues.json", "w") as f:
                json.dump(issue_list, f, indent="\t")
        # 2.2.5 Dump releases
        _,releases = get_paginated("https://api.github.com/repos/{}/{}/releases".format(organisation, repository['name']), headers=default_headers)
        # save json
        with open(archive_path / "releases.json", "w") as f:
            json.dump(releases, f, indent="\t")
        for release in releases:
            failed_downloads: list[dict] = []
            release_path = archive_path / "releases" / release['tag_name']
            release_path.mkdir(mode=0o755, parents=True, exist_ok=True)
            # download tarball
            file_name = release['tag_name'] + ".tar.gz"
            if not try_download(release['tarball_url'], release_path / file_name):
                failed_downloads.append({'url': release['tarball_url'], 'file': file_name})
            # download zip file
            file_name = release['tag_name'] + ".zip"
            if not try_download(release['zipball_url'], release_path / file_name):
                failed_downloads.append({'url': release['zipball_url'], 'file': file_name})
            # store assets
            for asset in release['assets']:
                if not try_download(asset['browser_download_url'], release_path / asset['name']):
                    failed_downloads.append({'url': asset['browser_download_url'], 'file': asset['name']})
            # Store failed downloads to file
            if failed_downloads:
                with open(release_path / "missing_downloads.json", "w") as f:
                    json.dump(failed_downloads, f, indent="\t")
    # 3. Clone projects
    _,projects = get_paginated("https://api.github.com/orgs/{}/projectsV2".format(organisation), headers=default_headers)
    for project in projects:
        # Get fields
        _,fields = get_paginated("https://api.github.com/orgs/{}/projectsV2/{}/fields".format(organisation,project['number']), headers=default_headers)
        project |= {'fields': fields}
        # Get items
        _,items = get_paginated("https://api.github.com/orgs/{}/projectsV2/{}/items".format(organisation,project['number']), headers=default_headers)
        project |= {'items': items}
        file_name = str(project['number']) + "_" + project['title'] + ".json"
        projects_path : Path = data_path / "archive" / "projects"
        projects_path.mkdir(mode=0o755, parents=True, exist_ok=True)
        with open(projects_path / file_name, "w") as f:
                json.dump(project, f, indent="\t")
    logger.info("Done")
