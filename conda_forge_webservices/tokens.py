import time
import base64
import os
import io
import sys
import logging
from contextlib import redirect_stdout, redirect_stderr

from typing import Any

from github import (
    Auth,
    Github,
    GithubIntegration,
    GithubException,
    InstallationAuthorization,
)

LOGGER = logging.getLogger("conda_forge_webservices.tokens")

FEEDSTOCK_TOKEN_RESET_TIMES: dict[str, Any] = {}
APP_TOKEN_RESET_TIME = None


def get_app_token_for_webservices_only():
    """Get's an app token that should only be used in the webservices bot.

    This function caches the token and only returns a new one when the current
    one is expired or about to expire in the next minute.

    Returns
    -------
    token: str
        The app token.
    """
    global APP_TOKEN_RESET_TIME
    global APP_TOKEN

    # add a minute to make sure token doesn't expire
    # while we are using it
    now = time.time()
    now_plus_1min = now + 60
    if APP_TOKEN_RESET_TIME is None or APP_TOKEN_RESET_TIME <= now_plus_1min:
        token = generate_app_token_for_webservices_only(
            os.environ["CF_WEBSERVICES_APP_ID"],
            os.environ["CF_WEBSERVICES_PRIVATE_KEY"].encode(),
        )
        if token is not None:
            try:
                APP_TOKEN_RESET_TIME = Github(token).rate_limiting_resettime
            except Exception:
                LOGGER.info("")
                LOGGER.info("===================================================")
                LOGGER.info("app token did not generate proper reset time")
                LOGGER.info("===================================================")
                token = None
        else:
            LOGGER.info("")
            LOGGER.info("===================================================")
            LOGGER.info("app token could not be made")
            LOGGER.info("===================================================")

        APP_TOKEN = token
    else:
        LOGGER.info("")
        LOGGER.info("===================================================")
        LOGGER.info(
            "app token exists - timeout %sm",
            (APP_TOKEN_RESET_TIME - now) / 60,
        )
        LOGGER.info("===================================================")

    assert APP_TOKEN is not None, "app token is None!"

    return APP_TOKEN


def generate_app_token_for_webservices_only(app_id, raw_pem):
    """Get an app token that should only be used in the webservices bot.

    Parameters
    ----------
    app_id : str
        The github app ID.
    raw_pem : bytes
        An app private key as bytes.

    Returns
    -------
    gh_token : str
        The github token. May return None if there is an error.
    """
    if "GITHUB_ACTIONS" in os.environ and os.environ["GITHUB_ACTIONS"] == "true":
        sys.stdout.flush()
        print(
            "running in github actions",
            flush=True,
        )
        print(f"::add-mask::{raw_pem}", flush=True)

    try:
        f = io.StringIO()
        if raw_pem[0:1] != b"-":
            with redirect_stdout(f), redirect_stderr(f):
                raw_pem = base64.b64decode(raw_pem)
            if (
                "GITHUB_ACTIONS" in os.environ
                and os.environ["GITHUB_ACTIONS"] == "true"
            ):
                sys.stdout.flush()
                print("base64 decoded PEM", flush=True)
                print(f"::add-mask::{raw_pem}", flush=True)

        if isinstance(raw_pem, bytes):
            with redirect_stdout(f), redirect_stderr(f):
                raw_pem = raw_pem.decode()
            if (
                "GITHUB_ACTIONS" in os.environ
                and os.environ["GITHUB_ACTIONS"] == "true"
            ):
                sys.stdout.flush()
                print("utf-8 decoded PEM", flush=True)
                print(f"::add-mask::{raw_pem}", flush=True)

        with redirect_stdout(f), redirect_stderr(f):
            gh_auth = Auth.AppAuth(app_id=app_id, private_key=raw_pem)
        if "GITHUB_ACTIONS" in os.environ and os.environ["GITHUB_ACTIONS"] == "true":
            sys.stdout.flush()
            print("loaded Github Auth", flush=True)

        with redirect_stdout(f), redirect_stderr(f):
            integration = GithubIntegration(auth=gh_auth)
        if "GITHUB_ACTIONS" in os.environ and os.environ["GITHUB_ACTIONS"] == "true":
            sys.stdout.flush()
            print("loaded Github Integration", flush=True)

        with redirect_stdout(f), redirect_stderr(f):
            installation = integration.get_org_installation("conda-forge")
        if "GITHUB_ACTIONS" in os.environ and os.environ["GITHUB_ACTIONS"] == "true":
            sys.stdout.flush()
            print("found Github installation", flush=True)

        with redirect_stdout(f), redirect_stderr(f):
            gh_token = integration.get_access_token(installation.id).token
        if "GITHUB_ACTIONS" in os.environ and os.environ["GITHUB_ACTIONS"] == "true":
            sys.stdout.flush()
            print("made GITHUB token and masking it for github actions", flush=True)
            print(f"::add-mask::{gh_token}", flush=True)

    except Exception:
        gh_token = None

    return gh_token


def inject_app_token_into_feedstock(full_name, repo=None):
    """Inject the cf-webservices-tokens app token into the repo secrets.

    Parameters
    ----------
    full_name : str
        The full name of the repo (e.g., "conda-forge/blah").
    repo : pygithub Repository
        Optional repo object to use. If not passed, a new one will be made.

    Returns
    -------
    injected : bool
        True if the token was injected, False otherwise.
    """
    repo_name = full_name.split("/")[1]

    # this is for testing - will turn it on for all repos later
    if repo_name not in [
        "cf-autotick-bot-test-package-feedstock",
        "conda-forge-pinning-feedstock",
    ]:
        return False

    if not repo_name.endswith("-feedstock"):
        return False

    global FEEDSTOCK_TOKEN_RESET_TIMES

    now = time.time()
    now_plus_30min = now + 30 * 60
    if FEEDSTOCK_TOKEN_RESET_TIMES.get(repo_name, now_plus_30min) <= now_plus_30min:
        token = generate_app_token_for_feedstock(
            os.environ["CF_WEBSERVICES_APP_ID"],
            os.environ["CF_WEBSERVICES_PRIVATE_KEY"].encode(),
            repo_name,
        )
        if token is not None:
            if repo is None:
                gh = Github(get_app_token_for_webservices_only())
                repo = gh.get_repo(full_name)
            try:
                repo.create_secret("RERENDERING_GITHUB_TOKEN", token)
                FEEDSTOCK_TOKEN_RESET_TIMES[repo_name] = Github(
                    token
                ).rate_limiting_resettime
                LOGGER.info("")
                LOGGER.info("===================================================")
                LOGGER.info(
                    "injected app token for repo %s - timeout %sm",
                    repo_name,
                    (FEEDSTOCK_TOKEN_RESET_TIMES[repo_name] - now) / 60,
                )
                LOGGER.info("===================================================")
                worked = True
            except Exception:
                LOGGER.info("")
                LOGGER.info("===================================================")
                LOGGER.info(
                    "app token could not be pushed to secrets for %s", repo_name
                )
                LOGGER.info("===================================================")
                worked = False

            return worked
        else:
            LOGGER.info("")
            LOGGER.info("===================================================")
            LOGGER.info("app token could not be made for %s", repo_name)
            LOGGER.info("===================================================")
            return False
    else:
        LOGGER.info("")
        LOGGER.info("===================================================")
        LOGGER.info(
            "app token exists for repo %s - timeout %sm",
            repo_name,
            (FEEDSTOCK_TOKEN_RESET_TIMES[repo_name] - now) / 60,
        )
        LOGGER.info("===================================================")
        return True


class MyGithubIntegration(GithubIntegration):
    def get_access_token(
        self,
        installation_id: int,
        permissions: dict[str, str] | None = None,
        repositories: list[str] | None = None,
    ) -> InstallationAuthorization:
        """
        :calls: `POST /app/installations/{installation_id}/access_tokens <https://docs.github.com/en/rest/apps/apps#create-an-installation-access-token-for-an-app>`
        """
        if permissions is None:
            permissions = {}

        if not isinstance(permissions, dict):
            raise GithubException(
                status=400, data={"message": "Invalid permissions"}, headers=None
            )

        body = {"permissions": permissions, "repositories": repositories}
        headers, response = self._GithubIntegration__requester.requestJsonAndCheck(
            "POST",
            f"/app/installations/{installation_id}/access_tokens",
            headers=self._get_headers(),
            input=body,
        )

        return InstallationAuthorization(
            requester=self._GithubIntegration__requester,
            headers=headers,
            attributes=response,
            completed=True,
        )


def generate_app_token_for_feedstock(app_id, raw_pem, repo):
    """Get an app token.

    Parameters
    ----------
    app_id : str
        The github app ID.
    raw_pem : bytes
        An app private key as bytes.
    repo : str
        The name of the repo for which the token is scoped.
        This should be like `ngmix-feedstock` without the org `conda-forge`
        in front.

    Returns
    -------
    gh_token : str
        The github token. May return None if there is an error.
    """
    if "GITHUB_ACTIONS" in os.environ and os.environ["GITHUB_ACTIONS"] == "true":
        sys.stdout.flush()
        print(
            "running in github actions",
            flush=True,
        )
        print(f"::add-mask::{raw_pem}", flush=True)

    try:
        f = io.StringIO()
        if raw_pem[0:1] != b"-":
            with redirect_stdout(f), redirect_stderr(f):
                raw_pem = base64.b64decode(raw_pem)
            if (
                "GITHUB_ACTIONS" in os.environ
                and os.environ["GITHUB_ACTIONS"] == "true"
            ):
                sys.stdout.flush()
                print("base64 decoded PEM", flush=True)
                print(f"::add-mask::{raw_pem}", flush=True)

        if isinstance(raw_pem, bytes):
            with redirect_stdout(f), redirect_stderr(f):
                raw_pem = raw_pem.decode()
            if (
                "GITHUB_ACTIONS" in os.environ
                and os.environ["GITHUB_ACTIONS"] == "true"
            ):
                sys.stdout.flush()
                print("utf-8 decoded PEM", flush=True)
                print(f"::add-mask::{raw_pem}", flush=True)

        with redirect_stdout(f), redirect_stderr(f):
            gh_auth = Auth.AppAuth(app_id=app_id, private_key=raw_pem)
        if "GITHUB_ACTIONS" in os.environ and os.environ["GITHUB_ACTIONS"] == "true":
            sys.stdout.flush()
            print("loaded Github Auth", flush=True)

        with redirect_stdout(f), redirect_stderr(f):
            integration = MyGithubIntegration(auth=gh_auth)
        if "GITHUB_ACTIONS" in os.environ and os.environ["GITHUB_ACTIONS"] == "true":
            sys.stdout.flush()
            print("loaded Github Integration", flush=True)

        with redirect_stdout(f), redirect_stderr(f):
            installation = integration.get_repo_installation("conda-forge", repo)
        if "GITHUB_ACTIONS" in os.environ and os.environ["GITHUB_ACTIONS"] == "true":
            sys.stdout.flush()
            print("found Github installation", flush=True)

        with redirect_stdout(f), redirect_stderr(f):
            gh_token_data = integration.get_access_token(
                installation.id,
                permissions={
                    "contents": "write",
                    "metadata": "read",
                    "workflows": "write",
                    "checks": "read",
                    "pull_requests": "write",
                    "statuses": "read",
                },
                repositories=[repo],
            )

            assert gh_token_data.permissions == {
                "contents": "write",
                "metadata": "read",
                "workflows": "write",
                "checks": "read",
                "pull_requests": "write",
                "statuses": "read",
            }, gh_token_data.permissions
            assert (
                gh_token_data.repository_selection == "selected"
            ), gh_token_data.repository_selection
            returned_repos = set(
                rp["name"] for rp in gh_token_data.raw_data["repositories"]
            )
            assert returned_repos == set([repo]), returned_repos

            gh_token = gh_token_data.token

        if "GITHUB_ACTIONS" in os.environ and os.environ["GITHUB_ACTIONS"] == "true":
            sys.stdout.flush()
            print("made GITHUB token and masking it for github actions", flush=True)
            print(f"::add-mask::{gh_token}", flush=True)

    except Exception as e:
        LOGGER.critical("error making token", exc_info=e)
        gh_token = None

    return gh_token
