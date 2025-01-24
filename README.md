<p align="center"><img src="mortician.png" style="width:40%;"/><br>A tool for quickly generating and editing postmortem reports.</p>

## Installation
1. Clone the project into a local directoy 
2. Use `pip install .` from the project directory to install.

## Usage
```
usage: mortician [-h] {create,edit,show} ...

Simple CLI for managing Postmortems

positional arguments:
    create            Create a new postmortem
    edit              Edit an existing postmortem
    show              Show details of a postmortem or list all postmortems

optional arguments:
  -h, --help          show this help message and exit
```
### Create Postmortems
```
usage: mortician create [-h] "your-postmortem-title" [--guide]

positional arguments:
  title    Title for the postmortem ##This will also generate a shorthand ID for the postmortem based on the title.

optional arguments:
  -h, --help  show this help message and exit
  --guide     Use guided creation mode
```

### Edit Postmortems
```
usage: mortician edit [-h] [--status STATUS] [--owner OWNER] [--participants PARTICIPANTS] [--summary SUMMARY] [--root_cause ROOT_CAUSE] [--temp_fix TEMP_FIX] [--perm_fix PERM_FIX] [--timeline]
                      [--add-entry KEY=VALUE [KEY=VALUE ...]]
                      issue_id

positional arguments:
  issue_id              Identifier for the postmortem

optional arguments:
  -h, --help            show this help message and exit
  --status STATUS       Update the status
  --owner OWNER         Update the incident owner
  --participants PARTICIPANTS
                        Update the participants
  --summary SUMMARY     Update the incident summary
  --root_cause ROOT_CAUSE
                        Update the root cause
  --temp_fix TEMP_FIX   Update the temporary fix
  --perm_fix PERM_FIX   Update the permanent fix
  --timeline            Indicate that timeline entries are being edited
  --add-entry KEY=VALUE [KEY=VALUE ...]
                        Add a new timeline entry (e.g. time=12:00 action='alert triggered')
```
### Filter Postmortems
```
usage: mortician show [-h] [--status STATUS] [--date DATE] [issue_id]

positional arguments:
  issue_id         Identifier for the postmortem (optional)

optional arguments:
  -h, --help       show this help message and exit
  --status STATUS  Filter postmortems by status (e.g., resolved, unresolved)
  --date DATE      Filter postmortems by date (e.g., 2023-08-15)
```

## Note
I am aware that a pathologist usually conducts post-mortems. Mortician is a much cooler name.
