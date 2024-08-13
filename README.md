# regerride
A tool to pull all the known package standards for a catalog and do a regex lookup and create override if desired.

### What is this repository for and when do I need to use this? ###

You don't need to unless it solves a workflow challenge involving the known_packages standard. This scrpt is intended to be used as an example of how a frequently requested product feature can be handled using the API. The known_package standard will trigger for all internal packages that a company uses, essentially any package that is unknown to the upstream repositories. This can create a lot of noise for companies that use a lot of internal packages and the request to be able to package name match via regex has been a common request for a few years. This script automates matching packages that have triggered the known_package standard in a catalog, creates an override for the packages that match and then writes the misses to a .csv report for further investigation. If you're unfamiliar with Regex, try asking Jeeves.

Note: Creating overrides in an automated fasion should be done with care. Start with patterns that you're confident with, review the packages that are misses and also audit the override export report to ensure that a packages override isn't being created for a truly unknown package. 

### How do I get set up? ###

* Ensure you have python 3.9 or higher installed 
* I recommend testing using a python virtual environment


### Configure Environment Variables ###

There are five variables that need to be set in order for the script to execute properly
* ORGANIZATION - Set in the script, scipt can be modified ot use it as an envar if desired
* CATALOG - Set in the script, scipt can be modified ot use it as an envar if desired
* [CATALOG_STANDARD](https://api.tidelift.com/docs/#tag/Catalogs/operation/listViolationsForCatalog) - This script is intended to be used with the `known_packages` standard but could be adapted to work with other standards
* TIDELIFT_API_KEY - This script requires a *user api key* which needs to be set as an environment variable and stored securly as a secret variable. 
* OVERRIDE_STATUS - an override can have a status of approved or denied

### Who do I talk to if I have questions? ###

* Larry Copeland
* [Team Customer Success](https://tidelift.slack.com/archives/C01EN3MKKBQ)