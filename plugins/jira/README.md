# Jira plugin for Wildland

Jira plugin for Wildland allows read-only representation of Jira issues as Wildland subcontainers.  
  
Each micro-container corresponding to a single issue is assigned the following categories:

- `/timeline/{year}/{month}/{day}/` - corresponding to the last modified date of the issue.
- `/labels/{label name}/` - corresponding to the labels assigned to the issue; (thus, a separate category will be created for each of the issue's labels).
- `/projects/{project name}/` - corresponding to the name of the project the issue is associated with.
- `/status/{status name}/` - corresponding to the status of the issue.

Additionally, the issue is accessible under any of the categories permutations (e.g. `/labels/{label_name}/@milestones/{milestone name}`).

### The content of an individual issue container
The directory representing the issue contains a single `{issue name}.md` file representing the issue's description.

### Getting started
You will need a Personal Access Token for your Atlassian account to be able to use this plugin. To generate one you can follow the tutorial [here][1] or go directly to API tokens management page in [Atlassian Account Settings][2]
### Creating container and storage

You first need to create a macro-container for exposing the issues:
```
wl container create jira-container --path /jira
```
You can then create storage that will be associated with said macro-container:
```
wl storage create jira --container jira-container \
                       --workspace-url <workspace-url> \
                       --personal-token <personal-token> \
                       --username <username> \
                       [--project-name <project-name>] \
                       [--project-name <project-name>]
```
- `--workspace-url` parameter specifies address of the REST endpoint of your _Jira Work Management Cloud site_ which will be queried for issues. For example https://{your site name}.atlassian.net/rest/api/2. The plugin works only with version v2 of Jira REST API.    
- `--username` parameter specifies Jira username  
- `--personal-token` parameter specifies your Personal Access Token generated in the previous steps.  
- `--project-name` is optional, multiple can be provided; when defined, only issues associated with the project (or projects) will be mounted. By default, all issues from the projects accessible by the user in the given _Jira Work Management Cloud site_ will be exposed.  
- `--limit` is optional, limits the maximum amount of issues to be fetched starting from the most recently updated  

### Mounting

To expose the issues, use the following command:
```
wl container mount --with-subcontainers jira-container
```

### Compatibility
The plugin works with version v2 of Jira REST API. At the moment of the creation of this plugin, v3 [is still in beta][3].

[1]: https://support.atlassian.com/atlassian-account/docs/manage-api-tokens-for-your-atlassian-account/
[2]: https://id.atlassian.com/manage/api-tokens
[3]: https://developer.atlassian.com/cloud/jira/platform/rest/v3/intro/#version



