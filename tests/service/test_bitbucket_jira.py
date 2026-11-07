import unittest
from unittest.mock import Mock

from agent_service.connectors.base import Comment, ResourceNotAllowed, Snapshot
from agent_service.connectors.bitbucket_jira import BitbucketJiraBackend


class DeliveryTest(unittest.TestCase):
    def setUp(self):
        self.bb = Mock()
        self.bb.fetch.return_value = Snapshot("bitbucket:pr", "pr", "v1",
                                              {"linked_jira_keys": ["KAN-8"]})
        self.jira = Mock(bot_identity="bot")
        self.jira.resolve_key.return_value = Snapshot("jira:10022", "jira", "j1", {})
        self.backend = BitbucketJiraBackend(self.bb, self.jira)
        self.store = Mock()
        self.store.resource.return_value = {"version": "v1"}
        self.backend.bind_store(self.store)

    def test_native_comment_identity_is_bound_to_target(self):
        self.jira.create_comment.return_value = "100"
        cid = self.backend.create_comment("bitbucket:pr", {"title": "Result"}, "marker")
        self.assertEqual(cid, "jira:10022|100")
        comment = Comment("100", "bot", "marker", "digest", 1)
        self.jira.list_comments.return_value = [comment]
        self.assertEqual(self.backend.list_comments("bitbucket:pr")[0].comment_id, cid)
        self.backend.update_comment("bitbucket:pr", cid, {}, "marker")
        self.jira.update_comment.assert_called_once_with("jira:10022", "100", {}, "marker")

    def test_changed_target_cannot_edit_old_issue(self):
        self.jira.resolve_key.return_value = Snapshot("jira:20000", "jira", "j2", {})
        with self.assertRaisesRegex(ResourceNotAllowed, "linked_jira_changed"):
            self.backend.update_comment("bitbucket:pr", "jira:10022|100", {}, "marker")
        self.jira.update_comment.assert_not_called()

    def test_missing_ambiguous_and_closed_links_are_refused(self):
        for keys in ([], ["KAN-8", "KAN-9"]):
            self.bb.fetch.return_value = Snapshot("bitbucket:pr", "pr", "v1",
                                                  {"linked_jira_keys": keys})
            with self.assertRaises(ResourceNotAllowed):
                self.backend.create_comment("bitbucket:pr", {}, "marker")
        self.jira.create_comment.assert_not_called()


    def test_changed_pr_version_cannot_choose_new_target_on_create(self):
        self.bb.fetch.return_value = Snapshot("bitbucket:pr", "pr", "v2",
                                              {"linked_jira_keys": ["KAN-9"]})
        with self.assertRaisesRegex(ResourceNotAllowed, "publication_source_changed"):
            self.backend.create_comment("bitbucket:pr", {}, "marker")
        self.jira.resolve_key.assert_not_called()
        self.jira.create_comment.assert_not_called()
