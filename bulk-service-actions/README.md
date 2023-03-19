# tnso-bulk-service-actions

# Table of Contents
1. [Purpose](#purpose)
2. [Action Summaries](#action-summaries)
3. [Settings](#settings)
    1. [Main Service Registration](#main-service-registration)
    2. [Target Sublayers](#target-sublayers)
    3. [Approved Diffs](#approved-diffs)
4. [Targets](#targets)
5. [Scheduler Service](#scheduler-service)
6. [Automatic Data Manipulation](#automatic-data-manipulation)
7. [Action Outputs](#action-outputs)
8. [Example Workflows](#example-workflows)
    1. [Redeploy all services of a particular type](#redeploy-all-of-type)
    2. [Redeploy services with diff approval](#redeploy-with-diff-approval)
    3. [Redeploy services with reconciliation](#redeploy-with-reconciliation)
    4. [Redeploy services with bsa-controller.py](#redeploy-with-controller)
    5. [Redeploy errored services with bsa-controller.py](#redeploy-with-controller-errors)


## Purpose: <a name="purpose"></a>

This package is a collection of actions designed to make mass service redeploys/reconciliations
easier. The actions are as follows with a brief summary of their purpose:

### Action summaries <a name="action-summaries"></a>
* *service-list*: This action needs to be run before any others. This action
takes either "populate" or "clear" as inputs, fairly self-explanatory. If populate, it
goes through services in /bulk-service-actions/settings/service-list/top-level-types and
compiles an entry for them under /bulk-service-actions/services. NOTE: Populating the
service-list can take several minutes if you are working with thousands of services each
with several modified sublayers.
<br/><br/>
* *redeploy-top-level*: This action allows you to redeploy one or more top-level services.
The dry-run option is enabled by default and the native dry-run output is pushed to
/bulk-service-actions/services. The redeploy-ready flag must be set for a particular
service instance in order to run redeploy-top-level with dry-run false. In general, top-level
services will be CFSes, but in practice you can specify anything.
<br/><br/>
* *reconcile-sublayers*: This action allows you to reconcile a top-level service's sublayer services
independently from the top-level service. The sublayer services to reconcile are defined as a leaf-list
in settings
<br/><br/>
* *service-list-tools*: This action allows the user to interact with the /bulk-service-action/
services list to a modest degree, allowing one to clear the data, set redeploy-ready
for selected services, and interact with approved diffs
<br/><br/>

### Settings: <a name="settings"></a>
There are a few attributes that must be set initially:

#### Main service registration (/bulk-service-actions/settings/service-list/top-level-types)  <a name="main-service-registration"></a>
This leaf-list allows you to configure which service types you'd like to interact with.
The format of the string should be given as a path to the main list of the service.
**MAKING A CHANGE HERE WILL DELETE THE CONTENTS OF /bulk-service-actions/services**:

    settings {
        service-list {
            top-level-types [ /services/bespoke/cfs-l2-p2p/service /services/bespoke/mbh/service ];
        }
    }

Some of the more common top-level service paths are as follows:

    /services/bespoke/mbh/service
    /services/bespoke/cfs-mp-2-mp/service
    /services/bespoke/cfs-l2-p2p/service
    /services/network/network-sync/device
    /services/network/network-sync/endpoint

#### Target sublayers (/bulk-service-actions/settings/service-list/target-sublayers) <a name="target-sublayers"></a>
The reconcile-sublayers action can be used to reconcile modified services of a particular
top-level service. Which services to include in this are defined here. Making a change here
will delete the contents of /bulk-service-actions/services.

    settings {
        service-list {
            target-sublayers [ ns-main-interface ns-service-instance rfs-vsi ];
        }
    }

#### Approved diffs <a name="approved-diffs"></a>
There is a list to keep track of diffs considered "safe" for redeploy at /bulk-service-actions/
approved-diffs. The list can be updated manually or interacted with via the service-list-tools
action. There is a leaf-list of wildcard strings at /bulk-service-actions/settings/diff-checking/
wildcard, these are regex expressions that will render as \*WILDCARD\<n\>\* in both the approved-diff
and dry-run output lists, this allows you to exclude interface names (for example) from dry-runs
to allow you to mark a diff as redeploy-ready even if it affects different interfaces on
different devices, for example:

    settings {
        diff-checking {
            wildcard [ "(HundredGigE|TenGigE|GigabitEthernet)\s?(\d\/){1,4}(\d*)\.?\d{1,4}" ];
        }
    }

Here are a few useful wildcards:

Common interface patterns:

    "(HundredGigE|TenGigE|GigabitEthernet)\s?(\d\/){1,4}(\d*)\.?\d{1,4}"
MBH service IDs:

    "(FB|MBH)-\d{3,10}"
IPv4 prefixes:

    "((25[0-5]|(2[0-4]|1\d|[1-9]|)\d)\.?\\b){4}(\/\d{1,2})?"
    (^for some reason we have to double escape \\b to get past the raw string in python)
Naive IPv6 prefixes:

    "([\dabcdef]){2,4}:.*? "
VRF/VLAN identifier

    "(vrf|vlan|VRF|VLAN)\s?\d{2,9}"

The original, unaltered dry-run output is kept in a debug hidden list called unaltered-output
which is next to the output list.  These values are kept in case the wildcard substitution
does unexpected things to the outputs. There is a leaf at service-list-tools/wildcards/operation
which can be set to "rollback" which will revert all the dry-run outputs to the original values.

### Targets <a name="targets"></a>
Most actions in the package reuse a common target specification scheme, allowing the user
to input a leaf-list of keypaths and/or the keyword "all". If no targets are specified
then all is assumed.

* *Keypath only*: If the user inputs only one or more keypaths those services will be the
target for the action.
<br/><br/>
* *Keypath + all*: If the user inputs one or more keypaths plus the keyword "all" then the
action will act on all services except those given in the keypath list.
<br/><br/>
* *All*: If the user inputs the keyword "all" only then the action will act on every service
in the /bulk-service-actions/services list.
<br/><br/>

An alternative is to set flags in targets/subset-of-all, which allows you to target only
services which have last-redeploy-error set, or no dry-run output, for example. These flags
are additive, so the total service list will be those services that match any of the flags.

### Scheduler service <a name="scheduler-service"></a>
There is a scheduler service to allow for scheduling runs of the redeploy-top-level and
reconcile-sublayers actions. The service instance is a list item under /bulk-service-actions/
activity and it takes basically the same set of arguments as the actions themselves (allowing
for various commit-flags and targets to be specified). In addition, a schedule argument for a
start time is provided as well as an interval argument (default 30) for a wait interval in
seconds between service redeploys.

The scheduler service takes the same target input scheme as detailed above, but importantly,
the scheduler service creates one scheduler instance (and hence one action execution) per
keypath given. This means that when running the action directly, the action will attempt to
redeploy all targeted services in the same transaction. Since redeploys can take some time,
it is easy to hit the action timeout (currently exceptionally set to 20 minutes for both
redeploy-top-level and reconcile-sublayers) if you specify many at once. For this reason,
it is preferable to use the scheduler service if running dozens or hundreds of redeploys.

### Automatic data manipulation <a name="automatic-data-manipulation"></a>
There are several cases where an action will automatically manipulate data in the
/bulk-service-actions/services list:

* If there is no native diff in the dry-run output of a redeploy then the redeploy-ready
flag is set automatically for that service.
* If all diffs for a service are in /bulk-service-actions/approved-diffs then the redeploy-
ready flag is set automatically for that service
* Last-redeploy-error is populated automatically with the result of the latest failure to
redeploy.
* Redeployed-at is populated with the timestamp of the latest successful redeploy.
* Dry-run output and last-redeploy-error (if populated) are both cleared after the a
successful redeploy.

### Action outputs <a name="action-outputs"></a>
The redeploy-top-level and reconcile-sublayers actions provide their outputs as a python set,
this is because there are various parts during the execution that can have different outputs,
so the logic simply appends the messages to the set and returns the whole set.

### Example workflows: <a name="example-workflows"></a>
<br/><br/>

#### Redeploy all services of a particular type: <a name="redeploy-all-of-type"></a>
##### 1) Define service type
    set bulk-service-actions settings service-list top-level-types [ /services/bespoke/mbh/service ]
    commit
##### 2) Populate service list
    request bulk-service-actions service-list populate
##### 3) Fetch dry-run output
    set bulk-service-actions activity REDEPLOY_MBH action redeploy-top-level
    set bulk-service-actions activity REDEPLOY_MBH commit-flags dry-run true
    set bulk-service-actions activity REDEPLOY_MBH schedule 2022-08-09T09:18:00
    commit
##### 4) Mark desired services as redeploy-ready
    request bulk-service-actions service-list-tools redeploy-ready { targets { all } }
##### 5) Redeploy services
    set bulk-service-actions activity REDEPLOY_MBH commit-flags dry-run false
    set bulk-service-actions activity REDEPLOY_MBH schedule 2022-08-09T09:30:00
    commit
##### 6) If not all services redeployed correctly the first time, we can optionally remove the successfully redeployed services
    request bulk-service-actions service-list clear redeployed-at
##### 7) Clean up service definition
    delete bulk-service-actions activity REDEPLOY_MBH
    commit
<br/><br/>

#### Redeploy services with diff approval: <a name="redeploy-with-diff-approval"></a>
##### Assuming service-list and settings are in place from previous example
##### 1) Optionally clear service-list of changes with no diff
##### In order to save time we can remove all services from the service-list which don't have a native dry-run output
    request bulk-service-actions service-list clear no-dry-run-diff
##### 2) Define wildcard string
##### Here we define a wildcard string which accepts diffs which affect multiple interfaces with differing service IDs
    set bulk-service-actions settings diff-checking wildcard [ "(HundredGigE|TenGigE|GigabitEthernet)\s?(\d\/){2,3}(\d.\d{1,4})" MBH-RER-FI-[12] ]
##### 3) Fetch dry-run output
    set bulk-service-actions activity REDEPLOY_MBH action redeploy-top-level
    set bulk-service-actions activity REDEPLOY_MBH commit-flags dry-run true
    set bulk-service-actions activity REDEPLOY_MBH schedule 2022-08-09T09:18:00
    commit
##### 4) Select diff as approved
##### Here we set the diff registered on service MBH-RER-FI-1 (wildcards included) as approved
    request bulk-service-actions service-list-tools diff-approval { approve-diff /ncs:services/struct:bespoke/mobile-backhaul:mbh/service{MBH-RER-FI-1} }
##### 5) Crosscheck dry-runs with approved diffs
##### Here we compare all dry-run outputs with approved diffs and mark as ready accordingly
    request bulk-service-actions service-list-tools diff-approval { check-approvals }
##### 6) Redeploy services
    set bulk-service-actions activity REDEPLOY_MBH commit-flags dry-run false
    set bulk-service-actions activity REDEPLOY_MBH schedule 2022-08-09T09:30:00
    commit
##### 7) Clean up service definition
    delete bulk-service-actions activity REDEPLOY_MBH
    commit
<br/><br/>

#### Redeploy services with sublayer-reconciliation <a name="redeploy-with-reconciliation"></a>
##### 1) Define modified-services which we are interested in
##### Here we define some sublayer services which we would like to reconcile
    set bulk-service-actions settings service-list target-sublayers [ ns-main-interface ns-service-instance rfs-vsi ]
##### 2) Populate service-list (the service-list is deleted any time service-settings are changed as in step 1 above)
    request bulk-service-actions service-list populate
##### 3) Fetch dry-run output for top-level service
    set bulk-service-actions activity REDEPLOY_MBH action redeploy-top-level
    set bulk-service-actions activity REDEPLOY_MBH commit-flags dry-run true
    set bulk-service-actions activity REDEPLOY_MBH schedule 2022-08-09T09:18:00
    commit
##### 4) Fetch dry-run output for sublayer reconciliation
    set bulk-service-actions activity RECONCILE_MBH action
    set bulk-service-actions activity RECONCILE_MBH action reconcile-sublayers
    set bulk-service-actions activity RECONCILE_MBH commit-flags dry-run true
    set bulk-service-actions activity RECONCILE_MBH schedule 2022-08-09T11:41:00-00:00
    commit
##### 5) Optionally redeploy top-level service
    set bulk-service-actions activity REDEPLOY_MBH commit-flags dry-run false
    set bulk-service-actions activity REDEPLOY_MBH schedule 2022-08-09T11:45:00
    commit
##### 6) Reconcile sublayers
    set bulk-service-actions activity RECONCILE_MBH commit-flags dry-run false
    set bulk-service-actions activity RECONCILE_MBH schedule 2022-08-09T11:49:00-00:00
    commit
##### 7) Clean up service definition
    delete bulk-service-actions activity REDEPLOY_MBH
    delete bulk-service-actions activity RECONCILE_MBH
    commit
<br/><br/>

#### Redeploy services with bsa-controller.py <a name="redeploy-with-controller"></a>
##### 1) Optionally create input file for services we want to affect
    [kwn3031@dev ~]$ cat service_list.txt
    /ncs:services/struct:bespoke/mobile-backhaul:mbh/service{FB-24003804}
    /ncs:services/struct:bespoke/mobile-backhaul:mbh/service{FB-24003814}
    /ncs:services/struct:bespoke/mobile-backhaul:mbh/service{FB-24004116}
    [kwn3031@dev ~]$
##### 2) Schedule dry-run redeploy of services
    [kwn3031@dev ~]$ python3 bsa-controller.py -f service_list.txt schedule-redeploy
    Scheduling a redeploy-top-level action with dry-run True and no-networking False for 2022-08-12T16:09:13.322913 [y/N]: y
    Activity bsa-controller_redeploy-top-level_1660313324 scheduled! See /bulk-service-actions/activity for details
    [kwn3031@dev ~]$
##### 3) Check dry-run outputs and mark services as redeploy-ready
    [kwn3031@dev ~]$ python3 bsa-controller.py -f service_list.txt display dry-run
    ...
    [kwn3031@dev ~]$ python3 bsa-controller.py -f service_list.txt edit-service-list mark-as-ready
    Services ... marked as redeploy-ready!
    [kwn3031@dev ~]$
##### 4) Schedule redeploy of services
    [kwn3031@dev ~]$ python3 bsa-controller.py -f service_list.txt schedule-redeploy --dry-run-false
    Scheduling a redeploy-top-level action with dry-run False and no-networking False for 2022-08-12T17:54:02.13323 [y/N]: y
    Activity bsa-controller_redeploy-top-level_1660315125 scheduled! See /bulk-service-actions/activity for details
    [kwn3031@dev ~]$
##### 5) Clean up scheduler activities
    delete bulk-service-actions activity bsa-controller_redeploy-top-level_1660313324
    delete bulk-service-actions activity bsa-controller_redeploy-top-level_1660315125
    commit
<br/><br/>

#### Redeploy only services with last-redeploy-error with bsa-controller.py <a name="redeploy-with-controller-errors"></a>
##### 1) Redeploy them!
    [kwn3031@dev ~]$ python3 bsa-controller.py schedule-redeploy -S last-redeploy-error
    Scheduling a redeploy-top-level action with dry-run True and no-networking False for 2022-08-13T12:16:46.270117. Confirm? [y/N]: y
    Activity bsa-controller_redeploy-top-level_1660385779 scheduled! See /bulk-service-actions/activity for details
    [kwn3031@dev ~]$
<br/><br/>

#### Known limitations: <a name="known-limitations"></a>

* There is currently no mechanism to ensure that a dry-run output is current or that the
redeploy-ready flag reflects the current state of the service. So, it is possible for a
dry-run to be given and redeploy-ready to be set but for the underlying service (and
therefore the dry-run diff) to be modified before the service is actually redeployed.

* The reconcile functionality is limited, for example there's no mechanism for marking
a reconcile as redeploy-ready or approving reconcile diffs like there are for normal
redeploys.

* Approved diffs are not topology-aware, so as long as all the diffs match with an
approved diff then the service is marked as redeploy-ready. Risk here is minimal for
most services.

* There is no cleanup function for scheduler services. After the scheduled run time you
must manually clean up the service definition under /bulk-service-actions/activity.

* Sometimes a scheduler entry fails with "application timeout" and thus the scheduler
entry sticks around even though the redeploy eventually ended up working. These can be
removed manually.

* I have seen an error "Error: Python cb_action error. Transaction not found (61): No
such transaction" during service-list population. It seems to be related to stale CFS
instances somehow and is usually gotten around by removing the service instance, not sure
how we will handle if we run into it in production.

* Some of the actions accept keypaths which are not in the service-list and return silently.
I.e. if you try to mark a keypath as ready that's not in the service-list it will return
the same as though it succeeded. Fixing would be a fair amount of work for not much benefit.

* The wildcards/update tool does not replace the approved-diff with the one with wildcards,
the old approved-diff needs to be deleted manually if desired.

# Controller script (bsa-controller.py) <a name="controller-script"></a>
The actions and data included here are designed for a very large number of services, potentially
everything on an instance. As such, the data presented and commands themselves are oftentimes
not very user-friendly from the NSO CLI, particularly specifying many services at once (since
they are identified by keypaths) and looking at dry-run outputs (since newlines are not
rendered as actual newlines in YANG strings).

With this in mind, there is a helper program called bsa-controller.py located under Scripts
which can help when dealing with a large number of services and viewing dry-run output in
a sensible way. The program is not exhaustively documented here, but is included in some
of the examples and has relatively good interactive help.

The bsa-controller.py script operates by running restconf calls towards the NSO server,
so if you have access to the server over the required ports from your local machine you can
run it from there, otherwise you can run it from the server itself too. Note that timestamps
generated by the script will be based on the time wherever the script is running, this can
cause problems if interacting with servers in different timezones than where the script is
running.
