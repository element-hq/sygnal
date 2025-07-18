# Contributing code to Sygnal

Everyone is welcome to contribute code to Sygnal, provided you are willing to
license your contributions under the same license as the project itself. In
this case, the [GNU Affero General Public License v3](LICENSE-AGPL-3.0).

### Installing dependencies

To contribute to Sygnal, ensure you have Python 3.8 or newer and then run:

Sygnal uses the [poetry](https://python-poetry.org/) project to manage its dependencies
and development environment. Once you have installed Python 3 and added the
source, you should install `poetry`.
Of their installation methods, we recommend
[installing `poetry` using `pipx`](https://python-poetry.org/docs/#installing-with-pipx),

```shell
pip install --user pipx
pipx install poetry
```

but see poetry's [installation instructions](https://python-poetry.org/docs/#installation)
for other installation methods.

Next, open a terminal and install dependencies as follows:

```sh
cd path/where/you/have/cloned/the/repository
poetry install
```

This will install the runtime and developer dependencies for the project.  Be sure to check
that the `poetry install` step completed cleanly.

### Run the tests

To make sure everything is working as expected, run the unit tests:

```bash
tox -e py
```

If you see a message like:

```
-------------------------------------------------------------------------------
Ran 46 tests in 0.209s

PASSED (successes=46)
___________________________________ summary ___________________________________
  py: commands succeeded
  congratulations :)
```

Then all is well and you're ready to work!

You can also directly run the tests using poetry.

```sh
poetry run trial tests
```

You can run unit tests in parallel by specifying `-jX` argument to `trial` where `X` is the number of parallel runners you want. To use 4 cpu cores, you would run them like:

```sh
poetry run trial -j4 tests
```

If you wish to only run *some* unit tests, you may specify
another module instead of `tests` - or a test class or a method:

```sh
poetry run trial tests.test_apns.ApnsTestCase.test_expected
```

## How to contribute

The preferred and easiest way to contribute changes is to fork the relevant
project on github, and then [create a pull request](
https://help.github.com/articles/using-pull-requests/) to ask us to pull your
changes into our repo.

Some other points to follow:

 * Please base your changes on the `main` branch.

 * Please follow the [code style requirements](#code-style).

 * Please include a [changelog entry](#changelog) with each PR.

 * Please [sign off](#sign-off) your contribution.

 * Please keep an eye on the pull request for feedback from the [continuous
   integration system](#continuous-integration-and-testing) and try to fix any
   errors that come up.

 * If you need to [update your PR](#updating-your-pull-request), just add new
   commits to your branch rather than rebasing.

## Code style

Sygnal follows the [Synapse code style].

[Synapse code style]: https://github.com/element-hq/synapse/blob/master/CONTRIBUTING.md

Many of the conventions are enforced by scripts which are run as part of the
[continuous integration system](#continuous-integration-and-testing).

To help check and fix adherence to the code style, you can run `tox`
locally. You'll need Python 3.8 or later:

```bash
# Run the code style check
tox -e check_codestyle

# Run the types check
tox -e check_types
```

These commands will consider the paths and files related to the project (i.e.
everything in `sygnal/` and in `tests/` as well as the `setup.py` file).

Before pushing new changes, ensure they don't produce linting errors. Commit any
files that were corrected.

Please ensure your changes match the cosmetic style of the existing project,
and **never** mix cosmetic and functional changes in the same commit, as it
makes it horribly hard to review otherwise.

## Further information on poetry

See the information provided in the [Synapse docs](https://github.com/element-hq/synapse/blob/master/docs/development/dependencies.md).

## Changelog

All changes, even minor ones, need a corresponding changelog / newsfragment
entry. These are managed by [Towncrier](https://github.com/hawkowl/towncrier).

To create a changelog entry, make a new file in the `changelog.d` directory named
in the format of `PRnumber.type`. The type can be one of the following:

* `feature`
* `bugfix`
* `docker` (for updates to the Docker image)
* `doc` (for updates to the documentation)
* `removal` (also used for deprecations)
* `misc` (for internal-only changes)

This file will become part of our [changelog](
https://github.com/element-hq/sygnal/blob/master/CHANGELOG.md) at the next
release, so the content of the file should be a short description of your
change in the same style as the rest of the changelog. The file can contain Markdown
formatting, and should end with a full stop (.) or an exclamation mark (!) for
consistency.

Adding credits to the changelog is encouraged, we value your
contributions and would like to have you shouted out in the release notes!

For example, a fix in PR #1234 would have its changelog entry in
`changelog.d/1234.bugfix`, and contain content like:

> The security levels of Florbs are now validated when received
> via the `/federation/florb` endpoint. Contributed by Jane Matrix.

If there are multiple pull requests involved in a single bugfix/feature/etc,
then the content for each `changelog.d` file should be the same. Towncrier will
merge the matching files together into a single changelog entry when we come to
release.

### How do I know what to call the changelog file before I create the PR?

Obviously, you don't know if you should call your newsfile
`1234.bugfix` or `5678.bugfix` until you create the PR, which leads to a
chicken-and-egg problem.

There are two options for solving this:

 1. Open the PR without a changelog file, see what number you got, and *then*
    add the changelog file to your branch (see [Updating your pull
    request](#updating-your-pull-request)), or:

 1. Look at the [list of all
    issues/PRs](https://github.com/element-hq/sygnal/issues?q=), add one to the
    highest number you see, and quickly open the PR before somebody else claims
    your number.

    [This
    script](https://github.com/richvdh/scripts/blob/master/next_github_number.sh)
    might be helpful if you find yourself doing this a lot.

Sorry, we know it's a bit fiddly, but it's *really* helpful for us when we come
to put together a release!

## Sign off

In order to have a concrete record that your contribution is intentional
and you agree to license it under the same terms as the project's license, we've adopted the
same lightweight approach that the Linux Kernel
[submitting patches process](
https://www.kernel.org/doc/html/latest/process/submitting-patches.html#sign-your-work-the-developer-s-certificate-of-origin>),
[Docker](https://github.com/docker/docker/blob/master/CONTRIBUTING.md), and many other
projects use: the DCO (Developer Certificate of Origin:
https://developercertificate.org/). This is a simple declaration that you wrote
the contribution or otherwise have the right to contribute it to Matrix:

```
Developer Certificate of Origin
Version 1.1

Copyright (C) 2004, 2006 The Linux Foundation and its contributors.
660 York Street, Suite 102,
San Francisco, CA 94110 USA

Everyone is permitted to copy and distribute verbatim copies of this
license document, but changing it is not allowed.

Developer's Certificate of Origin 1.1

By making a contribution to this project, I certify that:

(a) The contribution was created in whole or in part by me and I
    have the right to submit it under the open source license
    indicated in the file; or

(b) The contribution is based upon previous work that, to the best
    of my knowledge, is covered under an appropriate open source
    license and I have the right under that license to submit that
    work with modifications, whether created in whole or in part
    by me, under the same open source license (unless I am
    permitted to submit under a different license), as indicated
    in the file; or

(c) The contribution was provided directly to me by some other
    person who certified (a), (b) or (c) and I have not modified
    it.

(d) I understand and agree that this project and the contribution
    are public and that a record of the contribution (including all
    personal information I submit with it, including my sign-off) is
    maintained indefinitely and may be redistributed consistent with
    this project or the open source license(s) involved.
```

If you agree to this for your contribution, then all that's needed is to
include the line in your commit or pull request comment:

```
Signed-off-by: Your Name <your@email.example.org>
```

Git allows you to add this signoff automatically when using the `-s`
flag to `git commit`, which uses the name and email set in your
`user.name` and `user.email` git configs.

## Continuous integration and testing

[Buildkite](https://buildkite.com/matrix-dot-org/sygnal) will automatically
run a series of checks and tests against any PR which is opened against the
project; if your change breaks the build, this will be shown in GitHub, with
links to the build results. If your build fails, please try to fix the errors
and update your branch.

After installing tox with `pip install tox`, you can use the following to run
unit tests and lints in a local development environment:

- `tox -e py38` to run unit tests on Python 3.8.
- `tox -e check_codestyle` to check code style and formatting.
- `tox -e check_types` to check types with MyPy.
- `tox` **to do all of the above.**

### Testing proxy support

To test whether proxy support is working or not, a docker compose file has been
provided to make things easier.

**Note:** `podman` and `podman compose` commands also work instead of `docker` for these steps.
This may be preferable if root access is not available or desired.

For GCM Pushkin proxy testing follow these steps:
- build a docker image of sygnal named `localhost/sygnal`
- cd to `./scripts-dev/proxy-test/`
- **If you want to test with the real FCM service** (otherwise, skip these steps — the FCM service will be replaced with dummy responses):
  - create a firebase project & service account
  - download the service account file from firebase & save to `./scripts-dev/proxy-test/service_account.json`
  - configure the PROJECT_ID in `./scripts-dev/proxy-test/sygnal.yaml`
  - comment out the `map-local` lines in `docker-compose.yaml`
- run `./setup.sh`
- run `docker compose up`
- in another terminal, run `docker exec -it sygnal bash`
- run `./curl.sh`
- **If you are testing with the dummy FCM responses (default):**
  - expect to see a 200 OK response from Sygnal. If you get one, the proxy must be working.
- **If you are testing with the real FCM service**:
  - you can tell if the proxy is **NOT** working by inspecting the sygnal logs & seeing something along the lines of "Network is unreachable" or DNS resolution/proxy errors
  - you can tell if the proxy is working by inspecting the sygnal logs & seeing the following error from firebase '"code": 400, "message": "The registration token is not a valid FCM registration token"'
  - this is due to the `pushkey` being set to PUSHKEY_HERE in `notification.json`
  - if you want to fully test an actual notification, you will have to update this value in `./scripts-dev/proxy-test/notification.json` before calling `docker compose up`

## Updating your pull request

If you decide to make changes to your pull request - perhaps to address issues
raised in a review, or to fix problems highlighted by [continuous
integration](#continuous-integration-and-testing) - just add new commits to your
branch, and push to GitHub. The pull request will automatically be updated.

Please **avoid** rebasing your branch, especially once the PR has been
reviewed: doing so makes it very difficult for a reviewer to see what has
changed since a previous review.

## Conclusion

That's it! Matrix is a very open and collaborative project as you might expect
given our obsession with open communication. If we're going to successfully
matrix together all the fragmented communication technologies out there we are
reliant on contributions and collaboration from the community to do so. So
please get involved - and we hope you have as much fun hacking on Matrix as we
do!
