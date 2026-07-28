# pytest-lanes demo

Two lanes, each holding ~2 seconds of work. With the plugin installed:

```bash
pip install pytest-lanes[rich]
cd examples/demo
pytest .
```

The summary reports a parallelism ratio around 2x: both lanes ran at the
same time. To see the serial baseline, disable orchestration with the
plugin's kill-switch environment variable:

```bash
PYTEST_LANES_CHILD=1 pytest .          # bash
$env:PYTEST_LANES_CHILD = "1"; pytest . # PowerShell
```
