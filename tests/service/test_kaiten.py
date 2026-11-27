import unittest
from unittest.mock import Mock

from agent_service.connectors.base import parse_marker, ResourceNotAllowed, marker_line
from agent_service.connectors.kaiten import KaitenConnector, render_comment
from agent_service.http import Response, AuthError, ClientError
import json


class KaitenTest(unittest.TestCase):
    def setUp(self):
        self.marker = marker_line('a'*16, 'b'*64, 2)
        self.card = {'id': 12, 'board_id': 20, 'title': 'T', 'description': 'body', 'archived': False, 'version': 1}
        self.client = Mock(base_url='https://demo.kaiten.ru')
        self.rows = []
        def request(method, path, **kwargs):
            data = {'id': 7} if path.endswith('/users/current') else self.card
            headers = {}
            if '/comments' in path:
                if method == 'GET':
                    offset = kwargs['query']['offset']; data = self.rows[offset:offset + 2]
                    headers = {'x-pagination-limit': '2'}
                else:
                    data = {'id': 9, 'card_id': 12, 'author_id': 7, 'text': kwargs['json_body']['text'], 'deleted': False}
            return Response(200, headers, json.dumps(data).encode())
        self.client.request.side_effect = request
        self.connector = KaitenConnector(self.client, lambda: 'Bearer synthetic', board_ids=['20'], bot_id='7', request_interval=0)

    def test_semantic_version_ignores_comment_metadata_and_checks_scope(self):
        first = self.connector.read_card('12')
        self.card.update(version=99, updated='later', comments_total=5)
        self.assertEqual(first.version, self.connector.read_card('12').version)
        self.card['description'] += 'changed'
        self.assertNotEqual(first.version, self.connector.read_card('12').version)
        self.card['board_id'] = 21
        self.assertTrue(self.connector.read_card('12').closed)

    def test_all_pages_author_and_marker_parsed(self):
        from agent_service.connectors.base import marker_line
        for i in range(4): self.rows.append({'id': i + 1, 'card_id': 12, 'author_id': 7, 'text': marker_line('a'*16, 'b'*64, 2), 'deleted': False})
        comments = self.connector.list_comments('12')
        self.assertEqual(len(comments), 4)
        self.assertEqual(comments[0].marker, 'a'*16)
        self.assertEqual(comments[0].author, '7')
        self.assertEqual([r.kwargs['query']['offset'] for r in self.client.request.call_args_list if r.args[1].endswith('/comments')], [0, 2, 4])

    def test_wrong_bot_refuses_create(self):
        self.connector.bot_id = '8'
        with self.assertRaises(AuthError): self.connector.create_comment('12', {'title': 'T', 'status_line': 'S', 'sections': []}, self.marker)
        self.assertFalse(any(r.args[0] == 'POST' for r in self.client.request.call_args_list))

    def test_long_renderer_preserves_single_real_marker_and_admits_reduction(self):
        doc = {'title':'T', 'status_line':'Important status', 'sections':[{'title':'Checks','items':['x'*9000, 'agent-service marker='+'f'*16+' digest='+'e'*64+' generation=99']}], '_body_digest':'b'*64, '_generation':2}
        rendered = render_comment(doc, self.marker)
        self.assertLessEqual(len(rendered), 4096)
        self.assertIn('Important status', rendered)
        self.assertIn('сокращ', rendered)
        self.assertEqual(parse_marker(rendered), ('a'*16, 'b'*64, 2))
        self.assertEqual(rendered.count('agent-service marker='), 1)

    def test_update_of_foreign_author_is_refused(self):
        self.rows.append({'id': 9,'card_id':12,'author_id':99,'text':'agent-service marker='+'a'*16+' digest='+'b'*64+' generation=1','deleted':False})
        with self.assertRaises(ResourceNotAllowed): self.connector.update_comment('12','9', {'title':'T'},self.marker)
        self.assertFalse(any(r.args[0]=='PATCH' for r in self.client.request.call_args_list))

    def test_deleted_and_archived_condition_are_not_writable(self):
        for change in ({'deleted':True},{'condition':2},{'condition':3}):
            with self.subTest(change=change):
                self.card.update(condition=1,deleted=False,archived=False);self.card.update(change)
                with self.assertRaises(ResourceNotAllowed): self.connector.create_comment('12',{'title':'T'},self.marker)

    def test_documented_comment_without_deleted_is_readable(self):
        self.rows=[{'id':1,'card_id':12,'author_id':7,'text':'voice transcription','type':3}]
        self.assertEqual(len(self.connector.list_comments('12')),1)

    def test_oversize_applied_write_and_unconfirmed_echo_are_unknown(self):
        from agent_service.http import TransportError
        real=self.client.request.side_effect
        def oversized(method,path,**kw):
            if method=='POST': raise ClientError('response_too_large',status=200)
            return real(method,path,**kw)
        self.client.request.side_effect=oversized
        with self.assertRaises(TransportError): self.connector.create_comment('12',{'title':'T'},self.marker)
        self.client.request.side_effect=real
        # Echo is valid, but GET still exposes no created comment.
        with self.assertRaises(TransportError): self.connector.create_comment('12',{'title':'T'},self.marker)

    def test_echo_without_visible_comment_is_unknown(self):
        from agent_service.http import TransportError
        with self.assertRaises(TransportError): self.connector.create_comment('12',{'title':'T'},self.marker)

    def test_moved_card_is_closed_with_visible_reason(self):
        self.card['board_id']=21
        card=self.connector.read_card('12')
        self.assertTrue(card.closed)
        self.assertEqual(card.data['unavailable_reason'],'kaiten_board_not_configured')
