import os
os.chdir('jobs_run2')
jobs = os.listdir('.')
for job in jobs:
    os.system('nomad job stop -purge -yes \'' + job.replace('job', 'scan').replace('.hcl', '') + '\'' )