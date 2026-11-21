# npkext releases

Each GitHub Release has three downloads.

| Download | Requirements |
| --- | --- |
| `npkext-<version>-py3-none-any.whl` | Python 3.10 or newer on Windows or Ubuntu. Pip installs dependencies. |
| `npkext-<version>-windows-x64.zip` | Windows x64. Extract the archive and run `npkext.exe`. |
| `npkext-<version>-ubuntu-x64.tar.gz` | Ubuntu x64. Built on Ubuntu 22.04. Extract and run `./npkext`. |

Install the wheel with `python -m pip install <path-to-wheel>` from your
Python environment. For either standalone download, keep the executable
with its `_internal` folder. The standalone archive includes Python 3 and
the extractor's dependencies. For extraction examples, see
[command-line usage](usage.md).

## Build or publish a release

After pushing the workflow to the default branch, choose **Actions → Release
→ Run workflow** on GitHub to build test downloads. That run tests the shared
wheel and both standalone archives. Find the downloads in the run's artifacts.

To publish, push a tag that matches the version in `pyproject.toml`, such as
`v0.1.0`. The workflow builds and tests the assets and attaches all three to
one GitHub Release after the jobs pass.
