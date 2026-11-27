"""Opt-in same-origin browser boundary, independent of operator Bearer access."""
from html import escape
import hmac
import ipaddress
import json
from pathlib import Path
import sqlite3
import time
from urllib.parse import urlsplit, urlencode

from fastapi import Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, RedirectResponse, Response

from .ui_auth import AuthStore, UIError, USERNAME, SESSION_SECONDS, CHALLENGE_SECONDS
from .ui_scope import scope_for_service, validate_private_locations

WEB=Path(__file__).parent/'ui_web'
HEADERS={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'no-referrer',
         'Vary':'Cookie','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; form-action 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"}


def mount_ui(app,service,settings,auth=None):
    prefix = settings.path_prefix
    scope_for_service(service)
    validate_private_locations(settings,service)
    if auth is not None and auth.path.resolve()!=settings.database.resolve():raise ValueError('ui_auth_path_mismatch')
    auth=auth or AuthStore(settings.database,create=False)

    def cookie(response,key,value,max_age):
        response.set_cookie(key,value,max_age=max_age,path='/',secure=settings.secure,httponly=True,samesite='strict')

    def clear_cookie(response,key):
        response.delete_cookie(key,path='/',secure=settings.secure,httponly=True,samesite='strict')

    def current_scope():
        try:return scope_for_service(service)
        except ValueError:raise UIError('scope_changed',403) from None

    def actor(request):
        scope=current_scope()
        return auth.session(request.cookies.get(settings.cookie),scope.identity),scope

    @app.middleware('http')
    async def ui_boundary(request:Request,call_next):
        if request.url.path!=prefix and not request.url.path.startswith(prefix + '/'):
            return await call_next(request)
        # UI routes/assets have no variable path payloads: require canonical
        # raw paths so proxy and ASGI decoding cannot select different areas.
        if b'%' in request.scope.get('raw_path', b'').split(b'?', 1)[0]:
            return JSONResponse({'error':'not_found'},status_code=404,headers=HEADERS)
        if prefix == '/ui' and request.url.path.startswith('/ui/areas/'):
            return JSONResponse({'error':'not_found'},status_code=404,headers=HEADERS)
        try:
            hosts=request.headers.getlist('host')
            if len(hosts)!=1 or hosts[0].lower()!=urlsplit(settings.origin).netloc:raise UIError('invalid_host',421)
            if settings.allow_insecure_loopback:
                try:local_peer=request.client is not None and ipaddress.ip_address(request.client.host).is_loopback
                except ValueError:local_peer=False
                if not local_peer:raise UIError('loopback_peer_required',403)
            navigation=(request.method=='GET' and request.url.path in (prefix + '/result',prefix + '/login')
                        and request.headers.get('sec-fetch-mode')=='navigate'
                        and request.headers.get('sec-fetch-dest')=='document'
                        and request.headers.get('sec-fetch-user')=='?1')
            if request.headers.get('sec-fetch-site')=='cross-site' and not navigation:
                raise UIError('origin_rejected',403)
            if request.method not in ('GET','HEAD','OPTIONS'):
                origins=request.headers.getlist('origin')
                if len(origins)!=1 or origins[0]!=settings.origin:raise UIError('origin_rejected',403)
            if request.url.path.startswith(prefix + '/api/') and request.url.path not in (prefix + '/api/login',prefix + '/api/csrf'):
                request.state.ui_actor,request.state.ui_scope=await run_in_threadpool(actor,request)
                if request.url.path in (prefix + '/api/operations',prefix + '/api/connections') and request.state.ui_actor.role!='operator':
                    raise UIError('operator_required',403)
            response=await call_next(request)
        except UIError as exc:
            response=JSONResponse({'error':exc.code},status_code=exc.status)
            if exc.status==401 or exc.code=='scope_changed':clear_cookie(response,settings.cookie)
            if exc.status==429:response.headers['Retry-After']='900'
        except (sqlite3.Error,OSError):
            response=JSONResponse({'error':'ui_store_unavailable'},status_code=503)
        response.headers.update(HEADERS)
        return response

    async def login_body(request):
        content_type=request.headers.get('content-type','').split(';',1)[0].lower()
        if content_type!='application/json':raise UIError('json_required',415)
        declared=request.headers.get('content-length')
        if declared and (not declared.isascii() or not declared.isdigit() or len(declared)>6 or int(declared)>4096):
            raise UIError('request_too_large',413)
        body=bytearray()
        async for chunk in request.stream():
            body.extend(chunk)
            if len(body)>4096:raise UIError('request_too_large',413)
        try:
            data=json.loads(body)
            if (not isinstance(data,dict) or set(data)!={'username','password'}
                    or not isinstance(data['username'],str) or not USERNAME.fullmatch(data['username'])
                    or not isinstance(data['password'],str) or len(data['password'].encode('utf-8'))>1024):
                raise ValueError()
        except (ValueError,UnicodeError,TypeError):raise UIError('invalid_request',400) from None
        return data

    @app.get(prefix + '/api/csrf')
    async def csrf():
        challenge,token=await run_in_threadpool(auth.challenge)
        response=JSONResponse({'csrf':token})
        cookie(response,settings.challenge_cookie,challenge,CHALLENGE_SECONDS)
        return response

    @app.post(prefix + '/api/login')
    async def login(request:Request):
        data=await login_body(request)
        await run_in_threadpool(auth.consume_challenge,request.cookies.get(settings.challenge_cookie),request.headers.get('x-csrf-token'))
        scope=current_scope()
        token,_=await run_in_threadpool(auth.login,data['username'],data['password'],scope.identity,
            request.client.host if request.client else 'unknown',old_token=request.cookies.get(settings.cookie))
        response=JSONResponse({'authenticated':True})
        cookie(response,settings.cookie,token,SESSION_SECONDS);clear_cookie(response,settings.challenge_cookie)
        return response

    @app.get(prefix + '/api/me')
    async def me(request:Request):
        user=request.state.ui_actor;scope=request.state.ui_scope
        return {'username':user.username,'role':user.role,'csrf':user.csrf,'expires_at':user.expires_at,'valid_until':user.valid_until,
                'valid_for_seconds':max(0,user.valid_until-auth.clock()),
                'installation_id':scope.installation_id,'environment':scope.environment}

    @app.post(prefix + '/api/logout')
    async def logout(request:Request):
        supplied=request.headers.get('x-csrf-token','')
        if not hmac.compare_digest(supplied.encode('utf-8'),request.state.ui_actor.csrf.encode('utf-8')):
            raise UIError('csrf_rejected',403)
        await run_in_threadpool(auth.logout,request.cookies.get(settings.cookie))
        response=JSONResponse({'authenticated':False});clear_cookie(response,settings.cookie)
        return response

    @app.get(prefix + '/api/resources')
    async def resources(request:Request):
        value=request.query_params.get('limit','50')
        if not value.isascii() or not value.isdigit() or len(value)>3 or not 1<=int(value)<=100:
            raise UIError('invalid_limit',400)
        return await run_in_threadpool(service.store.ui_listing,request.state.ui_scope,int(value))

    @app.get(prefix + '/api/result')
    async def result(request:Request):
        rid=request.query_params.get('resource_id','')
        if not 1<=len(rid)<=512:raise UIError('invalid_resource_id',400)
        data=await run_in_threadpool(service.store.ui_result,request.state.ui_scope,rid)
        if data is None:raise UIError('resource_not_found',404)
        return data

    @app.get(prefix + '/api/view')
    async def view(request:Request):
        from .ui_views import workspace_view
        rid=request.query_params.get('resource_id')
        if rid is not None and not 1<=len(rid)<=512:raise UIError('invalid_resource_id',400)
        data=await run_in_threadpool(service.store.ui_workspace,request.state.ui_scope,rid)
        if data is None:raise UIError('resource_not_found',404)
        return {**workspace_view(data, path_prefix=prefix),'observed_at':time.time()}

    @app.get(prefix + '/api/operations')
    async def operations(request:Request):
        return await operator_data(request,'operations')

    @app.get(prefix + '/api/connections')
    async def connections(request:Request):
        return await operator_data(request,'connections')

    async def operator_data(request,section):
        from .ui_operator_views import operator_view
        data=await run_in_threadpool(service.store.ui_operator,request.state.ui_scope,getattr(service,'ui_metadata',None),section)
        return {**data,'result_html':operator_view(data,section,path_prefix=prefix),'observed_at':time.time()}

    @app.get(prefix)
    async def index(request:Request):
        try:await run_in_threadpool(actor,request)
        except UIError:return RedirectResponse(prefix + '/login',status_code=303)
        return RedirectResponse(prefix + '/changes',status_code=303)

    @app.get(prefix + '/changes')
    @app.get(prefix + '/result')
    @app.get(prefix + '/operations')
    @app.get(prefix + '/connections')
    async def workbench(request:Request):
        try:user,_=await run_in_threadpool(actor,request)
        except UIError:
            target=request.url.path+('?' +request.url.query if request.url.query else '')
            return RedirectResponse(prefix + '/login?'+urlencode({'next':target}),status_code=303)
        if request.url.path in (prefix + '/operations',prefix + '/connections') and user.role!='operator':
            raise UIError('operator_required',403)
        return web_response('workbench.html')

    @app.get(prefix + '/login')
    async def login_page():return web_response('login.html')

    @app.get(prefix + '/session')
    async def session_page(request:Request):
        try:await run_in_threadpool(actor,request)
        except UIError:return RedirectResponse(prefix + '/login',status_code=303)
        return web_response('session.html')

    @app.get(prefix + '/assets/{filename}')
    async def assets(filename:str):
        if filename not in ('ui.css','login.js','session.js','workbench.css','workbench.js','auth-events.js'):raise UIError('not_found',404)
        return web_response(filename)

    def web_response(filename):
        # These are packaged, trusted templates only, never analysis/result HTML.
        text = (WEB / filename).read_text().replace('/ui', prefix)
        if filename == 'auth-events.js':
            text = text.replace('impactmap-signout', 'impactmap-signout' + settings.cookie_suffix)
        if filename.endswith('.html') and settings.areas:
            links = ''.join('<a href="' + escape(a.path_prefix, quote=True) + '"'
                            + (' aria-current="page"' if a.path_prefix == prefix else '')
                            + '>' + escape(a.label) + '</a> ' for a in settings.areas)
            text = text.replace('<body>', '<body><nav aria-label="Области">' + links
                                + '<span>Для каждой области требуется отдельный вход.</span></nav>')
        kind = 'text/html' if filename.endswith('.html') else ('text/css' if filename.endswith('.css') else 'application/javascript')
        return Response(text, media_type=kind)
