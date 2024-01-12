import os
from teleprox import ProcessSpawner


print("Running from conda env:", os.environ['CONDA_DEFAULT_ENV'])

proc = ProcessSpawner(conda_env='teleprox2')

remote_os = proc.client._import('os')
print("Remote conda env:", remote_os.environ['CONDA_DEFAULT_ENV'])
