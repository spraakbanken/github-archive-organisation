import os
import subprocess
import json
import requests
import re

import logging

from time import strftime, time, sleep
from pathlib import Path
import json

import argparse

log_format : str = '%(asctime)s:%(levelname)s:%(name)s: %(message)s'
logger : logging.Logger = logging.getLogger(__name__)

def wait_for_reset(headers: dict) -> None:
    """Waits for the reset of the rate limit"""
    response : requests.Response = requests.get("https://api.github.com/rate_limit", headers=headers)
    rate_limit_state = response.json()
    logger.debug("Current rate limit: %s", str(rate_limit_state))
    # Avoid waiting if the reset just happened and we actually have new API calls
    if rate_limit_state['resources']['core']['remaining'] == 0:
        wait_seconds = round(rate_limit_state['resources']['core']['reset']-time.time()+0.01)
        logger.info("Wait for reset: %s seconds", str(wait_seconds))
        sleep(wait_seconds)
        return rate_limit_state['resources']['core']['limit']
    else:
        return rate_limit_state['resources']['core']['remaining'] 

def rate_limited_request(url : str, headers: dict, rate_limit_calls : int) -> (requests.Response, int):
    """Makes API calls respecting the rate limit by waiting for reseting of the limit if the number of calls exceeds it"""
    if rate_limit_calls == 0:
        rate_limit_calls = wait_for_reset(headers)
    return (requests.get(url, headers=default_headers), rate_limit_calls-1)

def get_paginated(url : str, headers: dict) -> (list[requests.Response],list[dict]):
    """Loads data from the Github API, accessing all the pages. Returns both the list of Response objects and the flattened list of JSON bodies as well as the number of api calls"""
    # Check the current rate limit
    response : requests.Response = requests.get("https://api.github.com/rate_limit", headers=headers)
    rate_limit_state = response.json()
    logger.debug("Current rate limit: %s", str(rate_limit_state))
    rate_limit_calls = rate_limit_state['resources']['core']['remaining']
    logger.info("Load %s", url)
    responses : list[requests.Response] = []
    link_regex : re.Pattern = re.compile('<(https://.*?)>; rel="next"')
    (response, rate_limit_calls) = rate_limited_request(url, headers, rate_limit_calls)
    responses.append(response)
    if 'link' in response.headers:
        urls : list[str] = response.headers['Link'].split(', ')
        for url in urls:
            match = link_regex.match(url)
            if match:
                next_url : str = match.group(1)
                logger.info("Load %s", next_url)
                if rate_limit_calls == 0:
                    rate_limit_calls = wait_for_reset(headers)
                (response, rate_limit_calls)  = rate_limited_request(next_url, headers, rate_limit_calls)
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
        logger.info("Clone %s into %s", re.sub("(//git:).*@","\\1<token>@",src), dest)
        working_dir = None
    logger.debug(' '.join(git_command))
    # Intialize Git LFS
    result = subprocess.run("git lfs install", shell=True)
    # Clone or fetch the repository
    result = subprocess.run(' '.join(git_command), shell=True,env={'GIT_SSH_COMMAND': ssh_command}, cwd=working_dir)
    if dest.exists():
        # Fetch LFS
        result = subprocess.run("git lfs fetch --all", shell=True, cwd=dest)
    return

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
    # Get token from environment if it exists
    if "GITHUB_TOKEN" in os.environ:
        token : str = os.environ["GITHUB_TOKEN"]
    else:
        token : str = ""
    # parse command line
    parser = argparse.ArgumentParser(
                    prog='archive-org.py',
                    description='Archives a Github organisation')
    parser.add_argument('--organisation', help="The organisation to archive, defaults to \"spraakbanken\"", type=str, default="spraakbanken")
    parser.add_argument('--data-dir', help="The output directory", type=str, required=True)
    parser.add_argument('--use-date', help="Flag to include date in the output path or not, defaults to include date", action=argparse.BooleanOptionalAction, default=True)
    parser.add_argument('--use-ssh', help="Flag to  use SSH to clone Git repositories or not, defaults to not use SSH", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument('--token', help="The fine-grained Github access token, defaults to GITHUB_TOKEN environment variable", type=str, default=token)
    parser.add_argument('--log-file', help="The log output file, defaults to archive.log", type=str, default="archive.log")
    parser.add_argument('-d', '--debug',
                    action='store_true')  # on/off flag
    args = parser.parse_args()
    organisation : str = args.organisation
    token : str = args.token
    data_dir : str = args.data_dir
    
    # Setup logging
    if args.debug:
        logging.basicConfig(level=logging.DEBUG, format=log_format)
    else:
        logging.basicConfig(level=logging.INFO, format=log_format, filename=args.log_file)

    default_headers = {"Accept": "application/vnd.github+json",  "Authorization": "Bearer {}".format(token), "X-GitHub-Api-Version": "2022-11-28"}
    
    logger.info("Start cloning %s", organisation)

    # 1. create output directory
    data_path : Path = Path(data_dir) / organisation
    if args.use_date:
        data_path = data_path / strftime("%Y%m%d-%H%M")
    data_path.mkdir(mode=0o755, parents=True, exist_ok=True)

    # 2. Archive repositories and archive organisation
    # 2.1. List all repositories
    _,repositories = get_paginated("https://api.github.com/orgs/{}/repos".format(organisation),headers=default_headers)
    repository_list : list[dict] = [{'name': repo['name'], 'url': repo['git_url'], 'has_issues': repo['has_issues'], 'has_wiki': repo['has_wiki'], 'json': repo} for repo in repositories]
    
    # 2.2. Clone repositories to archive organisation
    for repository in repository_list:
        archive_path = data_path / "archive" / repository['name']
        archive_path.mkdir(mode=0o755, parents=True, exist_ok=True)
        # 2.2.1 Archive repository infos
        with open(archive_path / "repository.json", "w") as f:
            json.dump(repository['json'], f, indent="\t")
        # 2.2.2 Clone repositories
        clone_path : Path = data_path / repository['name']
        if args.use_ssh:
            # Add SSH as Git protocol
            clone_repo("ssh+" + repository['url'], clone_path)
        else:
            # Replace Git by HTTPS and add username/password
            clone_repo(repository['url'].replace("git://","https://git:" + token + "@"), clone_path)
        # 2.2.3 Clone wikis
        if repository['has_wiki']:
            wiki_clone_path : Path = data_path / (repository['name'] + ".wiki")
            if args.use_ssh:
            # Add SSH as Git protocol, change repo to wiki
                wiki_url = "ssh+" + repository['url'].replace('.git','.wiki.git')
            else:
            # Replace Git by HTTPS and add username/password, change repo to wiki
                wiki_url = repository['url'].replace("git://", "https://git:" + token + "@").replace('.git','.wiki.git')
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
                comments = [t["body"] for t in timeline if t["event"] == "commented" and "body" in t]
                file_link_regex : re.Pattern = re.compile('\\((https://github.com/user-attachments/files/\\d+/([^)]+))\\)')
                # get attachments
                attachment_path = archive_path / "attachments"
                attachment_path.mkdir(mode=0o755, parents=True, exist_ok=True)
                failed_downloads: list[dict] = []
                for comment in comments:
                    link_match = file_link_regex.search(comment)
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
    # 3. Archive projects
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
