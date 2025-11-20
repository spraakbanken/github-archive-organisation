# github-archive-organisation

Python script to archive a complete organisation. It does the following
- lists all repositories and dumps their information as JSON
- clones all repositories using `git clone --mirror`
- dumps all issues as JSON including their timeline. This includes pull requests

## Setup

- You need a Github access token with the following permissions

- It only requires the python `requests` package. See `requirements.txt`
