# Repository Metrics

[![Build Status](https://dev.azure.com/best-practices/nlp/_apis/build/status/repo_metrics?branchName=master)](https://dev.azure.com/best-practices/nlp/_build/latest?definitionId=36&branchName=master)

We developed a script that allows us to track the metrics of the Recommenders repo. Some of the metrics we can track are listed here:

* Number of stars
* Number of forks
* Number of clones
* Number of views
* Number of lines of code

To see the full list of metrics, see [git_stats.py](git_stats.py)

The first step is to set up the credentials, copy the configuration file and fill up the credentials of GitHub and CosmosDB:

    cp tools/repo_metrics/config_template.py tools/repo_metrics/config.py

To track the current state of the repository and save it to CosmosDB:

    python tools/repo_metrics/track_metrics.py --github_repo "https://github.com/Microsoft/NLP" --save_to_database

To track an event related to this repository and save it to CosmosDB:

    python tools/repo_metrics/track_metrics.py --event "Today we did our first blog of the project" --event_date 2019-06-01 --save_to_database

### Setting up Azure CosmosDB

The API that we is used to track the GitHub metrics is the [Mongo API](https://docs.microsoft.com/en-us/azure/cosmos-db/mongodb-introduction).

The database name and collections name are defined in the [config file](config_template.py). There are two main collections, defined as `COLLECTION_GITHUB_STATS` and `COLLECTION_EVENTS` to store the information defined on the previous section. 

**IMPORTANT NOTE**: If the database and the collections are created directly through the portal, a common partition key should be defined. We recommend to use `date` as partition key.

