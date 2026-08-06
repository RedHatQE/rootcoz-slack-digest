"""Tests for URL builders."""

from rootcoz_slack_digest.links import jenkins_job_url, rootcoz_result_url


def test_rootcoz_result_url() -> None:
    url = rootcoz_result_url("https://rootcoz.example/", "abc/def")
    assert url == "https://rootcoz.example/results/abc%2Fdef"


def test_jenkins_job_url_with_build() -> None:
    url = jenkins_job_url("https://jenkins.example", "folder/job-a", 42)
    assert url == "https://jenkins.example/job/folder/job/job-a/42/"


def test_jenkins_job_url_empty_base() -> None:
    assert jenkins_job_url("", "job", 1) == ""
