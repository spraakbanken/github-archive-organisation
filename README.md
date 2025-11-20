# github-archive-organisation

Python script to archive a complete organisation. It does the following
- lists all repositories and dumps their information as JSON
- clones all repositories using `git clone --mirror`
- dumps all issues as JSON including their timeline. This includes pull requests

## Setup

- You need a Github access token with the following permissions
<img width="1408" height="724" alt="Screenshot 2025-11-20 at 15-26-15 Fine-grained Personal Access Token" src="https://github.com/user-attachments/assets/160191ff-fb4c-40de-b174-02fc929b913c" />

- It only requires the python `requests` package. See `requirements.txt`
