"""Fixed saved-state KRT audit. No application imports, refresh, calculation, or writes.

The support routes authenticate before importing this module. Roots and profiles
are trusted server constants, never filesystem or URL selectors from HTTP.
"""
from __future__ import annotations
import base64
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
from typing import Any
from urllib.parse import urlsplit

TARGET_DAY = '2026-11-08'
TARGET_PERIOD = int(dt.datetime(2026, 11, 8, tzinfo=dt.timezone.utc).timestamp())
MAX_FILE_BYTES = 16 * 1024 * 1024
MAX_TOTAL_READ_BYTES = 256 * 1024 * 1024
MAX_CAPTURE_BYTES = 23 * 1024 * 1024
MAX_FINANCE_RAW_BYTES = 16 * 1024 * 1024
ACCEPTED_FINANCE_SHA256 = '4732693f3f2b3c368a2af9a7975716844fe010e9de6abb6efcc48204fe7f9bf9'
MAX_FILES = 4000
FIXED_FILES = ('catalogue.json','decisions.json','ranking.json','schedule.json',
               'first_seen.json','watch_seen.json','rating_settings.json')
REQUIRED_FILES = ('catalogue.json','decisions.json','ranking.json','schedule.json')
FIXED_DIRS = ('reports','market-reports','decision_tep','decision_requirements')
DENIED_BASENAMES = frozenset({'auth.json','credentials.json','secrets.json','tokens.json','config.json'})
BASENAME = re.compile(r'[a-z0-9_-]{1,120}\.json\Z')
IDENTIFIER = re.compile(r'[a-z0-9:_-]{1,160}\Z')
HEX = re.compile(r'[a-f0-9]{32,128}\Z')
TEXT_FIELDS = frozenset({'slug','status','status_kind','last_known_status_kind',
    'id','document_id','title','name','address','okrug','district','department','matched_slug',
    'matched_name','kind','source_kind','engine_version','model_fingerprint','investment_rating_version'})
NUMBER_FIELDS = frozenset({'schema_version','published_at','retrieved_at','updated_at','computed_at',
    'market_computed_at','investment_rating_computed_at','catalogue_run_at','period',
    'started_at','finished_at','resumed_at','stopped_at','heartbeat_at','total','failed',
    'restarts','rules_version','investment_rating_target_rub_sqm','price_target_rub_sqm','area_ha',
    'housing_gfa_sqm','total_gfa_sqm','nonresidential_gfa_sqm','flats_sqm','nonresidential_ground_sqm',
    'checked_at','pages','pages_announced','seen','announced','brought','kept','accounted'})
BOOL_FIELDS = frozenset({'available','complete','stale','model_excluded','model_status_conflict',
    'early_unpublished','no_card','address_known','read'})


class AuditError(Exception):
    def __init__(self, code: str):
        self.code=code
        super().__init__(code)


def _utc_now():return dt.datetime.now(dt.timezone.utc)


def _reject_constant(_): raise AuditError('invalid_json')


def _pairs(values):
    result={}
    for key,value in values:
        if key in result: raise AuditError('invalid_json')
        result[key]=value
    return result


def _float(value):
    number=float(value)
    if not math.isfinite(number):raise AuditError('invalid_json')
    return number


def _json(raw):
    try:
        return json.loads(raw, object_pairs_hook=_pairs, parse_constant=_reject_constant,parse_float=_float)
    except (UnicodeError, ValueError, RecursionError):
        raise AuditError('invalid_json') from None


def _digest(raw): return hashlib.sha256(raw).hexdigest()


def _value_hash(value):
    return _digest(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode())


def _safe_text(value):
    if not isinstance(value,str) or len(value)>640:return None
    if re.search(r'\b(sk-(?:proj-)?|gh[pousr]_|AIza|AKIA)',value):raise AuditError('sensitive_field')
    if any(token in value.casefold() for token in ('private key','bearer ','api_key','token=', 'secret=')):
        raise AuditError('sensitive_field')
    if any(ord(char)<32 for char in value):raise AuditError('invalid_field')
    return value


def _metadata(value):
    if not isinstance(value,dict):return {'object_known':False}
    result={'object_known':True}
    for key in sorted(TEXT_FIELDS):
        if key in value:result[key]=_safe_text(value[key])
    # Original official URLs are needed for decision-publication identity.
    # Never export an authenticated/query-bearing/provider URL from a cache.
    for key in ('url','pdf_url'):
        if key not in value:continue
        url=_safe_text(value[key])
        if url:
            parts=urlsplit(url)
            if (parts.scheme not in {'http','https'} or not parts.hostname
                    or not (parts.hostname=='mos.ru' or parts.hostname.endswith('.mos.ru'))
                    or parts.username or parts.password or parts.query or parts.fragment):
                raise AuditError('unexpected_source_url')
        result[key]=url
    for key in sorted(NUMBER_FIELDS):
        if key in value:
            x=value[key]
            result[key]=x if type(x) in (int,float) and math.isfinite(x) else None
    for key in sorted(BOOL_FIELDS):
        if key in value:result[key]=value[key] if type(value[key]) is bool else None
    # Error strings may contain provider URLs/credentials; only existence/hash.
    for key in ('reason','stop_reason','stale_reason','market_failure_reason'):
        if key in value:
            result[key+'_present']=bool(value[key])
            result[key+'_sha256']=_value_hash(value[key])
    for key in ('investment_rating','model','screening'):
        if key in value:
            result[key+'_known']=isinstance(value[key],dict) and bool(value[key])
            result[key+'_sha256']=_value_hash(value[key])
    rating=value.get('investment_rating')
    if isinstance(rating,dict):
        result['rating_metadata']={k:rating[k] for k in ('available','computed_at','version')
            if k in rating and (type(rating[k]) in (bool,int,float) or
                (k=='version' and isinstance(rating[k],str) and _safe_text(rating[k]) is not None))}
    return result


def _rows(value):
    if not isinstance(value,list):return None
    if len(value)>MAX_FILES:raise AuditError('too_many_rows')
    return [_metadata(row) for row in value]


def _project(relative,value):
    result=_metadata(value)
    if not isinstance(value,dict):return result
    if relative=='catalogue.json': result['projects']=_rows(value.get('projects'))
    elif relative=='decisions.json':
        result['all']=_rows(value.get('all'))
        result['skipped_count']=len(value['skipped']) if isinstance(value.get('skipped'),list) else None
        result['walk']=_metadata(value.get('walk'))
    elif relative=='ranking.json': result['rows']=_rows(value.get('rows'))
    elif relative=='schedule.json':
        attempted=value.get('attempted')
        if isinstance(attempted,list):
            if len(attempted)>MAX_FILES:raise AuditError('too_many_rows')
            if any(not isinstance(s,str) or not IDENTIFIER.fullmatch(s) for s in attempted):
                raise AuditError('invalid_identifier')
            result['attempted']=list(attempted)
        else:result['attempted']=None
        result['immutable_input_cohort_present']=isinstance(value.get('input_cohort'),list)
        result['before_after_evidence_present']=isinstance(value.get('before_after'),dict)
    elif relative.startswith(('reports/','market-reports/')):
        result['project']=_metadata(value.get('project'))
        result['screening_metadata']=_metadata(value.get('screening'))
    return result


class Reader:
    def __init__(self,root:Path,profile="krt"):
        if profile not in {"krt","finance","aliases"}:raise AuditError("invalid_profile")
        self.profile=profile
        path=Path(root)
        if not path.is_absolute() or '..' in path.parts:raise AuditError('invalid_root')
        self.path=path
        self.total=0
        self.rootfd=os.open('/',os.O_RDONLY|os.O_DIRECTORY)
        try:
            for component in path.parts[1:]:
                descriptor=os.open(component,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=self.rootfd)
                os.close(self.rootfd);self.rootfd=descriptor
        except OSError:
            os.close(self.rootfd)
            raise AuditError('unsafe_root') from None

    def close(self):os.close(self.rootfd)

    def check_identity(self):
        """Refuse a namespace replaced while its old directory FD was pinned."""
        current=Reader(self.path,self.profile)
        try:
            before=os.fstat(self.rootfd);after=os.fstat(current.rootfd)
            if (before.st_dev,before.st_ino)!=(after.st_dev,after.st_ino):
                raise AuditError('snapshot_changed')
        finally:current.close()

    def _directory(self,component):
        allowed=FIXED_DIRS if self.profile=='krt' else ('baseline','estimate') if self.profile=='finance' else ()
        if component not in allowed:raise AuditError('invalid_path')
        try:return os.open(component,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=self.rootfd)
        except FileNotFoundError:return None
        except OSError:raise AuditError('unsafe_directory') from None

    def paths(self):
        if self.profile!='krt':raise AuditError('invalid_profile')
        result=list(FIXED_FILES)
        for directory in FIXED_DIRS:
            descriptor=self._directory(directory)
            if descriptor is None:continue
            try:
                names=[]
                with os.scandir(descriptor) as entries:
                    for entry in entries:
                        name=entry.name
                        if len(result)+len(names)>=MAX_FILES:raise AuditError('too_many_files')
                        if not BASENAME.fullmatch(name) or name.casefold() in DENIED_BASENAMES:
                            raise AuditError('unexpected_directory_entry')
                        names.append(name)
                result.extend(directory+'/'+name for name in sorted(names))
            finally:os.close(descriptor)
        if len(result)>MAX_FILES:raise AuditError('too_many_files')
        return result

    def read(self,relative,*,max_bytes=None):
        parts=relative.split('/')
        if self.profile=='krt':
            allowed=(relative in FIXED_FILES or
                len(parts)==2 and parts[0] in FIXED_DIRS and
                BASENAME.fullmatch(parts[1]) and parts[1].casefold() not in DENIED_BASENAMES)
        elif self.profile=='aliases':
            allowed=relative=='.aliases.json'
        else:
            allowed=(relative in {'baseline/finance.xlsx','baseline/finance_meta.json'} or
                re.fullmatch(r'estimate/[0-9]{4}-[0-9]{2}-[0-9]{2}\.(?:xlsx|json)',relative))
        if not allowed:raise AuditError('invalid_path')
        limit=MAX_FILE_BYTES
        if self.profile=='aliases' or self.profile=='finance' and relative.endswith('.json'):
            limit=min(limit,65536)
        if max_bytes is not None:
            if type(max_bytes) is not int or max_bytes<0:raise AuditError('invalid_limit')
            limit=min(limit,max_bytes)
        size_error='file_too_large' if self.profile=='krt' else 'source_size_limit'
        parent=self.rootfd
        child=None
        try:
            if len(parts)==2:
                child=self._directory(parts[0]);parent=child
                if child is None:return None
            try:descriptor=os.open(parts[-1],os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent)
            except FileNotFoundError:return None
            except OSError:raise AuditError('unsafe_file') from None
            try:
                before=os.fstat(descriptor)
                if not stat.S_ISREG(before.st_mode) or before.st_nlink!=1:raise AuditError('not_regular')
                if before.st_size>limit:raise AuditError(size_error)
                chunks=[];size=0
                while True:
                    chunk=os.read(descriptor,min(65536,limit+1-size))
                    if not chunk:break
                    chunks.append(chunk);size+=len(chunk);self.total+=len(chunk)
                    if size>limit:raise AuditError(size_error)
                    if self.total>MAX_TOTAL_READ_BYTES:raise AuditError('read_budget')
                after=os.fstat(descriptor)
                if (before.st_ino,before.st_size,before.st_mtime_ns)!=(after.st_ino,after.st_size,after.st_mtime_ns):
                    raise AuditError('file_changed_during_read')
                raw=b''.join(chunks)
                return raw,{'bytes':size,'sha256':_digest(raw),
                    'mtime_ns':after.st_mtime_ns,'inode':after.st_ino}
            finally:os.close(descriptor)
        finally:
            if child is not None:os.close(child)


def capture_krt(root:Path,*,runtime:dict[str,Any],now:dt.datetime|None=None,process:dict|None=None,purpose='krt_cached_metadata_v1'):
    runtime=_runtime(runtime)
    if purpose not in {'krt_cached_metadata_v1','krt_cached_replay_v1'}:raise AuditError('invalid_purpose')
    now=now or _utc_now()
    if now.utcoffset()!=dt.timedelta(0):raise AuditError('invalid_time')
    reader=Reader(root)
    try:
        paths=reader.paths();files=[];first={};decoded={};projected_bytes=0
        for relative in paths:
            read=reader.read(relative)
            if read is None:first[relative]=None;continue
            raw,metadata=read;first[relative]=metadata
            parsed=_json(raw);projection=_project(relative,parsed)
            if purpose=='krt_cached_replay_v1':
                projection['structured_blocks']=_replay_blocks(relative,parsed)
            if relative in {'catalogue.json','schedule.json'}:decoded[relative]=projection
            record={'logical_path':'krt/'+relative,**metadata,'projection':projection}
            projected_bytes+=len(json.dumps(record,ensure_ascii=False,allow_nan=False).encode())+2
            if projected_bytes>MAX_CAPTURE_BYTES:
                raise AuditError('source_size_limit')
            files.append(record)
        if reader.paths()!=paths:raise AuditError('file_set_changed')
        for relative in paths:
            second=reader.read(relative)
            if first[relative]!=(None if second is None else second[1]):
                raise AuditError('snapshot_changed')
        reader.check_identity()
        missing=[path for path in FIXED_FILES if first[path] is None]
        catalogue=decoded.get('catalogue.json');schedule=decoded.get('schedule.json')
        stamp=catalogue.get('retrieved_at') if isinstance(catalogue,dict) else None
        valid_stamp=type(stamp) in (int,float) and math.isfinite(stamp) and 0<stamp<=now.timestamp()
        process_observation=_process_metadata(process)
        gaps=['sunday_input_revision_not_proven','excluded_models_before_after_not_proven',
              'weekly_stdout_logs_not_persisted_by_this_collector',
              'early_projects_require_exact_runtime_source',
              'other_worker_refresh_state_not_observed']
        refresh_flags=[process_observation[key] for key in ('catalogue_refreshing','decisions_refreshing')]
        if any(flag is None for flag in refresh_flags):gaps.append('runtime_refresh_flags_not_captured')
        if any(flag is True for flag in refresh_flags):gaps.append('observed_worker_refreshing')
        missing_required=[name for name in missing if name in REQUIRED_FILES]
        missing_optional=[name for name in missing if name not in REQUIRED_FILES]
        if missing_required:gaps.append('required_saved_files_missing')
        if missing_optional:gaps.append('optional_saved_files_absent')
        expected_schemas={'catalogue.json':3,'decisions.json':3,'ranking.json':1}
        by_path={v['logical_path'][4:]:v['projection'] for v in files}
        for name,expected_schema in expected_schemas.items():
            if by_path.get(name,{}).get('schema_version')!=expected_schema:
                gaps.append(name.removesuffix('.json')+'_schema_unknown_or_unsupported')
        if not valid_stamp or now.timestamp()-stamp>86400:gaps.append('catalogue_stale_or_timestamp_unknown')
        period=schedule.get('period') if isinstance(schedule,dict) else None
        if type(period) not in (int,float) or period!=TARGET_PERIOD:gaps.append('saved_schedule_is_not_target_sunday')
        output={'schema':1,'purpose':purpose,'runtime':runtime,'process_observation':process_observation,
            'captured_at_utc':now.isoformat(),'target_sunday':TARGET_DAY,'target_period':TARGET_PERIOD,
            'coherent':True,'files':files,'missing_files':missing,
            'missing_required_files':missing_required,'missing_optional_files':missing_optional,'gaps':gaps,
            'evidence_complete':False,'production_acceptance':False,
            'reads_only':True,'models_or_scores_computed':False,'source_files_written':False}
        encoded=json.dumps(output,ensure_ascii=False,allow_nan=False).encode()
        if len(encoded)>MAX_CAPTURE_BYTES:raise AuditError('capture_too_large')
        return output
    finally:reader.close()


def after_admission(authorize, root_factory, runtime_factory, *, now=None):
    """Support-route adapter: authorization must finish before root/runtime I/O."""
    authorize()
    return capture_krt(root_factory(), runtime=runtime_factory(), now=now)


# These are native financial structures, not general report/LLM envelopes.
SCREENING_BLOCKS=frozenset({'available','preliminary','traffic_light','tep_ratios','model_inputs',
    'requirements','renovation','programme','market','phasing','absorption','metrics',
    'entry_capacity','at_asking_price'})
RATING_BLOCKS=frozenset({'investment_rating','investment_rating_version',
    'investment_rating_computed_at','investment_rating_target_rub_sqm','investment_rating_segment',
    'available','computed_at','rules_version','engine_version','model_fingerprint','traffic_light',
    'saleable_sqm','segment','start_price_rub_sqm','project_llcr_x','weakest_phase_llcr_x',
    'margin_pct','net_profit_mln','phase_count','at_asking_price','burden_pct','burden_mln',
    'ordinary_capex_mln','burden_pipeline_version','burden_checked_at','burden_pending',
    'burden_complete','burden_components','burden_llcr_x','burden_entry_capacity_mln'})
FORBIDDEN_KEYS=frozenset({'auth','authorization','headers','cookies','credentials','api_key','key',
    'token','secret','password','private_key','prompt','prompts','messages','instructions',
    'system_prompt','request_body','response_body','conversation','thread_id','session','session_id',
    'text','headline','quote','note','notes','content','body','raw','raw_text','source_text'})
SENSITIVE_FRAGMENTS=('prompt','credential','secret','password','private_key','authorization',
    'access_token','refresh_token','api_key','cookie','request_header','response_header','raw_request',
    'raw_response','thread_id','session_id')
FORBIDDEN_COMPACT=frozenset(re.sub(r'[^a-z0-9]','',key) for key in FORBIDDEN_KEYS)


def _scrub(value,depth=0,budget=None):
    if budget is None:budget=[300000]
    budget[0]-=1
    if budget[0]<0 or depth>64:raise AuditError('structured_limit')
    if isinstance(value,dict):
        out={}
        for key,item in value.items():
            word=str(key).casefold().replace('-','_')
            compact=re.sub(r'[^a-z0-9]','',word)
            if (word in FORBIDDEN_KEYS or compact in FORBIDDEN_COMPACT
                    or any(fragment in word for fragment in SENSITIVE_FRAGMENTS)
                    or compact.startswith('auth') and compact.endswith(('token','key','header','headers','secret'))
                    or any(fragment in compact for fragment in ('prompt','credential','password','privatekey',
                        'authorization','accesstoken','refreshtoken','apikey','cookie','threadid','sessionid'))):continue
            out[key]=_scrub(item,depth+1,budget)
        return out
    if isinstance(value,list):return [_scrub(item,depth+1,budget) for item in value]
    if isinstance(value,str):
        if (any(marker in value.casefold() for marker in ('private key','bearer ','secret=','api_key='))
                or re.search(r'\b(sk-(?:proj-)?|gh[pousr]_|AIza|AKIA)',value)):
            raise AuditError('sensitive_field')
    return value


def _replay_blocks(relative,value):
    if not isinstance(value,dict):return {'known':False}
    if relative=='ranking.json':
        rows=value.get('rows')
        return {'rows':None if not isinstance(rows,list) else [
            {'slug':_safe_text(row.get('slug')),
             'rating_and_model':_scrub({k:row[k] for k in RATING_BLOCKS if k in row})}
            if isinstance(row,dict) else {'known':False} for row in rows]}
    if relative.startswith('reports/'):
        screening=value.get('screening')
        return {'screening':None if not isinstance(screening,dict) else
            _scrub({k:screening[k] for k in SCREENING_BLOCKS if k in screening})}
    return {}


def _process_metadata(value):
    value=value if isinstance(value,dict) else {}
    result={'scope':'one_worker_observation_not_global_state'}
    for key in ('catalogue_refreshing','decisions_refreshing'):
        result[key]=value.get(key) if type(value.get(key)) is bool else None
    fingerprint=value.get('model_fingerprint_cached')
    result['model_fingerprint_cached']=fingerprint if isinstance(fingerprint,str) and HEX.fullmatch(fingerprint) else None
    rules=value.get('screening_rules_version')
    result['screening_rules_version']=rules if type(rules) is int and rules>=0 else None
    return result


def parse_request(raw:bytes,kind:str,*,today:dt.date|None=None):
    """Strict business inputs after the existing realm admission, no I/O."""
    if not isinstance(raw,bytes) or len(raw)>16384:raise AuditError('invalid_request')
    value=_json(raw)
    if not isinstance(value,dict):raise AuditError('invalid_request')
    allowed={'key','session','purpose'} if kind=='krt' else {'key','session','purpose','project','cut'}
    if set(value)-allowed:raise AuditError('invalid_request')
    for key in ('key','session'):
        if key in value and (not isinstance(value[key],str) or len(value[key])>4096):
            raise AuditError('invalid_request')
    if kind=='krt':
        if value.get('purpose') not in {'krt_cached_metadata_v1','krt_cached_replay_v1'}:
            raise AuditError('invalid_purpose')
        return {'purpose':value['purpose']}
    if kind!='finance' or value.get('purpose')!='finance_sources_v1':raise AuditError('invalid_purpose')
    project=value.get('project')
    if (not isinstance(project,str) or not project.strip() or len(project)>200
            or any(char in project for char in ('/','\\','\0')) or project.strip() in {'.','..'}):
        raise AuditError('invalid_project')
    cut=value.get('cut')
    try:parsed=dt.date.fromisoformat(cut) if isinstance(cut,str) else None
    except ValueError:raise AuditError('invalid_cut') from None
    today=today or _utc_now().date()
    if parsed is None or parsed.isoformat()!=cut or parsed>today:raise AuditError('unsupported_cut')
    return {'purpose':value['purpose'],'project':project.strip(),'cut':cut}


def _runtime(value):
    if (not isinstance(value,dict) or set(value)!={'commit','version'}
            or not isinstance(value['commit'],str) or not re.fullmatch('[a-f0-9]{40}',value['commit'])
            or not isinstance(value['version'],str) or not re.fullmatch(r'\d+\.\d+\.\d+',value['version'])):
        raise AuditError('invalid_runtime')
    return dict(value)


def _namespace(value):
    if not isinstance(value,str) or not re.fullmatch(r'[0-9a-zA-Zа-яА-ЯёЁ _-]{1,64}',value):
        raise AuditError('unsafe_project_identity')
    if value in {'.','..'}:raise AuditError('unsafe_project_identity')
    return value


def _estimate_members(reader):
    descriptor=reader._directory('estimate')
    if descriptor is None:return []
    try:
        names=[];count=0
        with os.scandir(descriptor) as entries:
            for entry in entries:
                count+=1
                if count>MAX_FILES:raise AuditError('too_many_files')
                if entry.name.endswith('.xlsx'):
                    stem=entry.name[:-5]
                    try:day=dt.date.fromisoformat(stem)
                    except ValueError:raise AuditError('invalid_estimate_name') from None
                    if day.isoformat()!=stem:raise AuditError('invalid_estimate_name')
                    names.append(entry.name)
        return sorted(names)
    finally:os.close(descriptor)


def _meta_projection(raw,kind):
    value=_json(raw)
    if not isinstance(value,dict):raise AuditError('invalid_source_metadata')
    allowed=('file_name','uploaded_at','taken_at') if kind=='finance' else ('filename','loaded_at','taken_at','bytes')
    result={}
    for key in allowed:
        if key not in value:continue
        item=value[key]
        if key=='bytes':result[key]=item if type(item) is int and item>=0 else None
        else:result[key]=_safe_text(item)
    return result


def capture_finance(root:Path,*,runtime:dict[str,Any],project:str,cut:str,slug_function,now:dt.datetime|None=None):
    """Only current stored FM+meta and one dated RSS+meta. No parsers/caches."""
    runtime=_runtime(runtime);now=now or _utc_now()
    if now.utcoffset()!=dt.timedelta(0):raise AuditError('invalid_time')
    inputs=parse_request(json.dumps({'purpose':'finance_sources_v1','project':project,'cut':cut}).encode(),
        'finance',today=now.date())
    # The pure namespace function is supplied by existing Monitor, not guessed here.
    original=_namespace(slug_function(inputs['project']))
    aliases_reader=Reader(root,'aliases');reader=None
    try:
        aliases=aliases_reader.read('.aliases.json')
        mapping={}
        if aliases is not None:
            value=_json(aliases[0])
            if not isinstance(value,dict) or not isinstance(value.get('aliases'),dict):raise AuditError('invalid_aliases')
            mapping=value['aliases']
        selected=_namespace(mapping.get(original,original))
        if selected in mapping and mapping[selected]!=selected:raise AuditError('alias_chain_not_supported')
        base=os.path.normpath(root);target=os.path.normpath(os.path.join(base,selected))
        if not target.startswith(base+os.sep) or os.path.dirname(target)!=base:
            raise AuditError('unsafe_project_identity')
        reader=Reader(Path(target),'finance')
        members=_estimate_members(reader)
        eligible=[name for name in members if name[:-5]<=cut]
        estimate=eligible[-1] if eligible else None
        paths=['baseline/finance.xlsx','baseline/finance_meta.json']
        if estimate:paths.extend(['estimate/'+estimate,'estimate/'+estimate[:-5]+'.json'])
        collected=[];first={};raw_total=0;gaps=[];fm_meta=None
        for relative in paths:
            found=reader.read(relative,max_bytes=MAX_FINANCE_RAW_BYTES-raw_total if relative.endswith('.xlsx') else None)
            first[relative]=None if found is None else found[1]
            slot=('finance' if relative.endswith('finance.xlsx') else 'finance_meta' if relative.endswith('finance_meta.json')
                  else 'bank_rss' if relative.endswith('.xlsx') else 'bank_rss_meta')
            if found is None:
                gaps.append(slot+'_missing');continue
            raw,metadata=found;record={'slot':slot,'logical_path':relative,**metadata}
            if relative.endswith('.xlsx'):
                raw_total+=len(raw)
                if raw_total>MAX_FINANCE_RAW_BYTES:raise AuditError('source_size_limit')
                record['content_base64']=base64.b64encode(raw).decode('ascii')
            else:
                if len(raw)>65536:raise AuditError('source_size_limit')
                record['metadata']=_meta_projection(raw,'finance' if slot=='finance_meta' else 'estimate')
                if slot=='finance_meta':fm_meta=record['metadata']
            collected.append(record)
        if estimate is None:gaps.append('bank_rss_missing_at_cut')
        finance=next((r for r in collected if r['slot']=='finance'),None)
        if finance is not None and finance['sha256']!=ACCEPTED_FINANCE_SHA256:gaps.append('accepted_finance_source_mismatch')
        if fm_meta is not None:
            day=fm_meta.get('taken_at')
            try:source_day=dt.date.fromisoformat(day) if isinstance(day,str) else None
            except ValueError:source_day=None
            if source_day is None or source_day.isoformat()!=day:gaps.append('finance_effective_date_unknown')
            elif source_day>dt.date.fromisoformat(cut):gaps.append('finance_not_supported_at_cut')
        bank_meta=next((r for r in collected if r['slot']=='bank_rss_meta'),None)
        bank=next((r for r in collected if r['slot']=='bank_rss'),None)
        if bank_meta is not None:
            if bank_meta['metadata'].get('taken_at')!=(None if estimate is None else estimate[:-5]):
                gaps.append('bank_rss_meta_date_mismatch_or_unknown')
            if bank is not None and bank_meta['metadata'].get('bytes')!=bank['bytes']:
                gaps.append('bank_rss_meta_size_mismatch_or_unknown')
        if [n for n in _estimate_members(reader) if n[:-5]<=cut]!=eligible:raise AuditError('snapshot_changed')
        second_total=0
        for relative in paths:
            again=reader.read(relative,max_bytes=MAX_FINANCE_RAW_BYTES-second_total if relative.endswith('.xlsx') else None)
            if again is not None and relative.endswith('.xlsx'):second_total+=len(again[0])
            if first[relative]!=(None if again is None else again[1]):raise AuditError('snapshot_changed')
        aliases_after=aliases_reader.read('.aliases.json')
        if (None if aliases is None else aliases[1])!=(None if aliases_after is None else aliases_after[1]):
            raise AuditError('snapshot_changed')
        reader.check_identity();aliases_reader.check_identity()
        result={'schema':1,'purpose':'finance_sources_v1','runtime':runtime,'captured_at_utc':now.isoformat(),
            'project':inputs['project'],'namespace':selected,'cut':cut,'bank_rss_date':None if estimate is None else estimate[:-5],
            'identity':{'requested_slug':original,'resolved_slug':selected,
                'aliases_sha256':None if aliases is None else aliases[1]['sha256']},
            'coherent':True,'files':collected,'gaps':gaps,'evidence_complete':False,
            'financial_acceptance':False,'reads_only':True,'source_files_written':False,
            'paid_through_date':None,'paid_through_not_inferred_from_upload_or_filename':True}
        if len(json.dumps(result,ensure_ascii=False,allow_nan=False).encode())>MAX_CAPTURE_BYTES:
            raise AuditError('source_size_limit')
        return result
    finally:
        aliases_reader.close()
        if reader is not None:reader.close()
