"""Lane-based subprocess orchestration for pytest suites with heavy infrastructure.

A "lane" is a group of tests that share a marker and an execution environment
(a database container, a service singleton, a build step). The plugin runs one
pytest subprocess per lane in parallel, so each environment is paid for once
and never shared across processes. See README.md for the configuration schema.
"""

__version__ = "0.2.0"
