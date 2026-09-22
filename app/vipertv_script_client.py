"""Tiny dependency-free client for ViperTV Scripted Scheduling.

Scheduler programs launched by ViperTV automatically receive:
  VIPERTV_API_BASE, VIPERTV_API_TOKEN, VIPERTV_BUILD_ID,
  VIPERTV_MODE and VIPERTV_ARGS_JSON.
"""
from __future__ import annotations
import json, os, urllib.parse, urllib.request

BASE=os.environ.get('VIPERTV_API_BASE','http://127.0.0.1:8409').rstrip('/')
TOKEN=os.environ.get('VIPERTV_API_TOKEN','')
BUILD_ID=os.environ.get('VIPERTV_BUILD_ID','')
MODE=os.environ.get('VIPERTV_MODE','build')
ARGS=json.loads(os.environ.get('VIPERTV_ARGS_JSON','[]') or '[]')

def request(method,path,data=None):
    body=None if data is None else json.dumps(data).encode()
    req=urllib.request.Request(BASE+path,data=body,method=method,headers={'Authorization':'Bearer '+TOKEN,'Content-Type':'application/json','Accept':'application/json'})
    with urllib.request.urlopen(req,timeout=60) as r:return json.loads(r.read().decode())

def get(path):return request('GET',path)
def post(path,data=None):return request('POST',path,data or {})
def channels():return get('/api/v1/scripted/channels')['channels']
def schedules():return get('/api/v1/scripted/schedules')['schedules']
def search(query,limit=100):return get('/api/v1/scripted/catalog?'+urllib.parse.urlencode({'query':query,'limit':limit}))['items']
def replace_items(schedule_id,items):return post(f'/api/v1/scripted/schedules/{int(schedule_id)}/replace-items',{'items':items})
def graphics_events(schedule_id,events):return post(f'/api/v1/scripted/schedules/{int(schedule_id)}/graphics-events',{'events':events})
def assign(channel_id,schedule_id):return post(f'/api/v1/scripted/channels/{int(channel_id)}/assign',{'schedule_id':int(schedule_id)})
def reset(channel_id):return post(f'/api/v1/scripted/channels/{int(channel_id)}/reset',{})
