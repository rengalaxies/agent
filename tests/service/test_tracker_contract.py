import unittest

from agent_service.connectors.base import PublicationBackend, ResourceNotAllowed
from agent_service.connectors.bitbucket_jira import BitbucketJiraBackend
from agent_service.connectors.tracker_contract import TaskIdentity, CommentIdentity, semantic_version


class TrackerContractTest(unittest.TestCase):
    def test_identity_scopes_and_opaque_ids_roundtrip(self):
        a = TaskIdentity('yandex_tracker', 'cloud:org-a', 'issue|長:id')
        c = CommentIdentity(a, '900719925474099312345|opaque')
        self.assertEqual(CommentIdentity.decode(c.encode(), expected=a), c)
        for b in (TaskIdentity('yandex_tracker', 'cloud:org-b', a.native_id),
                  TaskIdentity('kaiten', 'org-a.kaiten.ru', a.native_id)):
            self.assertNotEqual(a, b)
            with self.assertRaises(ResourceNotAllowed):
                CommentIdentity.decode(c.encode(), expected=b)

    def test_invalid_identity_never_normalizes_to_another(self):
        for value in (None, 123, True, '', 'a\n', 'x' * 301):
            with self.assertRaises(ValueError):
                TaskIdentity('kaiten', 'org.kaiten.ru', value)
        with self.assertRaises(ValueError):
            TaskIdentity('unknown', 'org', '1')
        for raw in ('', 'tracker-comment:v2:[]', 'tracker-comment:v1:["kaiten"]'):
            with self.assertRaises(ValueError):
                CommentIdentity.decode(raw)

    def test_version_tracks_full_semantic_content_and_scope_not_comment_noise(self):
        a = TaskIdentity('kaiten', 'org.kaiten.ru', '12')
        fields = {'title': 'T', 'description': 'x' * 22000, 'updated': 1, 'comments_total': 0}
        names = ('title', 'description')
        original = semantic_version(a, fields, names)
        fields.update(updated=2, comments_total=1, version=99)
        self.assertEqual(original, semantic_version(a, fields, names))
        fields['description'] += 'changed past truncation boundary'
        changed = semantic_version(a, fields, names)
        self.assertNotEqual(original, changed)
        self.assertNotEqual(changed, semantic_version(a, fields, names, closed=True))
        self.assertNotEqual(changed, semantic_version(TaskIdentity('kaiten', 'other', '12'), fields, names))

    def test_existing_jira_facade_satisfies_publication_protocol(self):
        self.assertIsInstance(BitbucketJiraBackend(None, None), PublicationBackend)
