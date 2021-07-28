# Wildland backend for exposing GitLab issues as FS
This plugin allows read-only access to GitLab project issues and exposing them as a number of sub-containers.

The individual micro-container corresponding to a single issue is assigned the following categories:

- `/timeline/{year}/{month}/{day}/` - corresponding to the last modified date of the issue.
- `/labels/{label name}/` - corresponding to the labels assigned to the issue; (thus, a separate category will be created for each of the issue's labels).
- `/projects/{project name}/` - corresponding to the name of the project the issue is associated with.
- `/milestones/{milestone name}/` - corresponding to the milestone the issue has been assigned.

Additionally, the issue is accessible under any of the categories permutations (e.g. `/labels/{label_name}/@milestones/{milestone name}`).

## The content of an individual issue container

The directory representing the issue contains a single `{issue name}.md` file representing the issue's description.

## Initializing and mounting

### Getting started

To be able to create GitLab storage, you first need to generate a Personal Access Token that will later on be passed as a `--personal-token` parameter. To do so, simply follow the steps outlined [here][1].

### Creating a macro-container and storage

You first need to create a macro-container for exposing the issues:
```
wl container create gitlab-container --path /gitlab
```
You can then create storage that will be associated with said macro-container:
```
wl storage create gitlab-graphql --container gitlab-container \
                                 --personal-token <token> \
                                 [--project-path <projectpath>]
```
`--personal-token` parameter specifies your Personal Access Token generated in the previous steps.
`--project-path` is optional; when provided, only the issues associated with the project will be accessed. Otherwise, all issues associated with all projects that the user is a member of will be exposed.

### Mounting

To expose the issues, use the following command:
```
wl container mount --with-subcontainers gitlab-container
```

[1]: https://docs.gitlab.com/ee/user/profile/personal_access_tokens.html




