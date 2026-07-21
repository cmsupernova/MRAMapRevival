(function(global){
  'use strict';
  const LS_KEY='mra_unified_v1';
  const TP_NS='tp';
  const SUPABASE_URL='https://msnxqnqqpdwamzfbwskm.supabase.co';
  const SUPABASE_ANON_KEY='sb_publishable_MjRmbztlv0wlOQXpTvoBlQ__BJobsxC';
  const TABLE='placements';

  function base(value){
    return String(value||'').replace(/^.*[\\/]/,'').replace(/\.SEC$/i,'');
  }
  function key(sectorBase,x,y){
    return base(sectorBase)+':'+Number(x)+':'+Number(y);
  }
  function cellId(sectorBase,x,y){
    return TP_NS+':'+key(sectorBase,x,y);
  }
  function parseCell(cell){
    const s=String(cell||'');
    if(!s.startsWith(TP_NS+':')) return null;
    const rest=s.slice(TP_NS.length+1);
    const parts=rest.split(':');
    if(parts.length<3) return null;
    const y=+parts.pop(), x=+parts.pop(), sectorBase=parts.join(':');
    if(!sectorBase||!Number.isFinite(x)||!Number.isFinite(y)) return null;
    return {sector_base:base(sectorBase),x,y,key:key(sectorBase,x,y)};
  }
  function normalize(value,fallbackKey){
    if(typeof value==='string') value={name:value};
    if(!value||typeof value!=='object') return null;
    let sectorBase=value.sector_base, x=value.x, y=value.y;
    if(x==null) x=value.col;
    if(y==null) y=value.row;
    const parts=String(fallbackKey||'').split(':');
    if((sectorBase==null||x==null||y==null)&&parts.length>=3){
      sectorBase=parts.slice(0,-2).join(':');
      x=parts[parts.length-2];
      y=parts[parts.length-1];
    }
    const name=String(value.name||'').trim().toUpperCase();
    if(!name||!base(sectorBase)||!Number.isFinite(+x)||!Number.isFinite(+y)) return null;
    return {
      key:key(sectorBase,+x,+y),
      value:{
        name,
        sector_base:base(sectorBase),
        x:+x,
        y:+y,
        subtype:+value.subtype||1,
        grade:value.grade||value._grade||'DERIVED'
      }
    };
  }
  function fromRegistry(registry){
    const out={};
    const rows=registry&&registry.teleportals;
    if(!rows||typeof rows!=='object') return out;
    Object.entries(rows).forEach(([name,row])=>{
      if(!row||row._inactive||row._alias_for) return;
      const n=normalize(Object.assign({},row,{name}),null);
      if(n) out[n.key]=n.value;
    });
    return out;
  }
  function normalizeBag(source){
    const out={};
    if(!source||typeof source!=='object') return out;
    Object.entries(source).forEach(([k,v])=>{
      const n=normalize(v,k);
      if(n) out[n.key]=n.value;
    });
    return out;
  }
  function fromRemoteRows(rows){
    const out={};
    (rows||[]).forEach(row=>{
      const parsed=parseCell(row&&row.cell);
      if(!parsed) return;
      const name=String(row.filename||'').trim().toUpperCase();
      if(!name||name==='__cleared__') return;
      out[parsed.key]={
        name,
        sector_base:parsed.sector_base,
        x:parsed.x,
        y:parsed.y,
        subtype:1,
        grade:row.place_name||'DERIVED'
      };
    });
    return out;
  }
  function load(){
    const out=fromRegistry(global.TELEPORTAL_REGISTRY||{});
    try{
      const bag=JSON.parse(localStorage.getItem(LS_KEY)||'{}');
      Object.assign(out,normalizeBag(bag.teleportalLabels||bag.teleportal_labels||{}));
    }catch(_e){}
    return out;
  }
  function save(labels){
    let bag={};
    try{ bag=JSON.parse(localStorage.getItem(LS_KEY)||'{}'); }catch(_e){}
    bag.teleportalLabels=normalizeBag(labels||{});
    localStorage.setItem(LS_KEY,JSON.stringify(bag));
    return bag.teleportalLabels;
  }
  function importAny(raw,current){
    const out=Object.assign({},current||{});
    if(!raw||typeof raw!=='object') return out;
    let incoming=raw.teleportalLabels||raw.teleportal_labels;
    if(!incoming&&raw.labels) incoming=raw.labels;
    if(!incoming&&raw.teleportals) return Object.assign(out,fromRegistry(raw));
    return Object.assign(out,normalizeBag(incoming||{}));
  }
  function set(labels,sectorBase,x,y,name,grade){
    const out=Object.assign({},labels||{});
    const k=key(sectorBase,x,y);
    name=String(name||'').trim().toUpperCase();
    if(!name) delete out[k];
    else out[k]={name,sector_base:base(sectorBase),x:+x,y:+y,subtype:1,grade:grade||'DERIVED'};
    return out;
  }
  function defaultPrefix(sectorBase){
    const letters=base(sectorBase).toUpperCase().replace(/[^A-Z0-9]/g,'').replace(/[0-9]/g,'');
    return (letters||'TPX').slice(0,3).padEnd(3,'X');
  }
  function autoName(labels,sectorBase){
    const prefix=defaultPrefix(sectorBase);
    const used=new Set(Object.values(labels||{}).map(v=>String(v&&v.name||'').toUpperCase()));
    let n=1, name=prefix+'_'+n;
    while(used.has(name)){ n++; name=prefix+'_'+n; }
    return name;
  }
  function handleName(){
    return localStorage.getItem('mra_name')||'anon';
  }

  const Sync={
    client:null,
    ready:false,
    listeners:[],
    onChange(fn){ if(typeof fn==='function') this.listeners.push(fn); },
    emit(labels,meta){ this.listeners.forEach(fn=>{ try{ fn(labels,meta); }catch(_e){} }); },
    cfg(){
      return {
        url: localStorage.getItem('mra_url')||SUPABASE_URL,
        key: localStorage.getItem('mra_key')||SUPABASE_ANON_KEY,
        name: handleName()
      };
    },
    async connect(){
      if(!global.supabase){ this.ready=false; return {ok:false,error:'no supabase'}; }
      const c=this.cfg();
      if(!c.url||!c.key){ this.ready=false; return {ok:false,error:'missing config'}; }
      try{
        this.client=global.supabase.createClient(c.url,c.key,{realtime:{params:{eventsPerSecond:5}}});
        const {data,error}=await this.client.from(TABLE).select('*').like('cell', TP_NS+':%');
        if(error) throw error;
        const remote=fromRemoteRows(data||[]);
        const merged=Object.assign(load(),remote);
        save(merged);
        this.client.channel('rt-teleportals').on('postgres_changes',{
          event:'*', schema:'public', table:TABLE
        },p=>{
          const cell=((p.new||p.old)||{}).cell||'';
          if(!String(cell).startsWith(TP_NS+':')) return;
          const parsed=parseCell(cell);
          if(!parsed) return;
          let labels=load();
          if(p.eventType==='DELETE'||!(p.new&&p.new.filename)||p.new.filename==='__cleared__'){
            delete labels[parsed.key];
          } else {
            labels[parsed.key]={
              name:String(p.new.filename).trim().toUpperCase(),
              sector_base:parsed.sector_base,
              x:parsed.x,
              y:parsed.y,
              subtype:1,
              grade:p.new.place_name||'DERIVED'
            };
          }
          save(labels);
          this.emit(labels,{source:'realtime',cell});
        }).subscribe();
        this.ready=true;
        this.emit(merged,{source:'pull',count:Object.keys(remote).length});
        return {ok:true,count:Object.keys(remote).length,labels:merged};
      }catch(e){
        this.ready=false;
        console.error('teleportal supabase connect failed', e);
        return {ok:false,error:e};
      }
    },
    async upsert(label){
      if(!this.ready||!this.client||!label||!label.name) return;
      const row={
        cell:cellId(label.sector_base,label.x,label.y),
        filename:String(label.name).toUpperCase(),
        mp_x:+label.x,
        mp_y:+label.y,
        layer:'tp',
        mp_z:50,
        place_name:label.grade||'DERIVED',
        updated_by:handleName(),
        updated_at:new Date().toISOString()
      };
      const {error}=await this.client.from(TABLE).upsert(row);
      if(error) console.error('teleportal upsert failed', error);
      return !error;
    },
    async remove(sectorBase,x,y){
      if(!this.ready||!this.client) return;
      const {error}=await this.client.from(TABLE).delete().eq('cell', cellId(sectorBase,x,y));
      if(error) console.error('teleportal delete failed', error);
      return !error;
    },
    async pushAll(labels){
      if(!this.ready||!this.client) return {ok:false,count:0};
      const list=Object.values(normalizeBag(labels||{}));
      let n=0;
      for(const label of list){
        if(await this.upsert(label)) n++;
      }
      return {ok:true,count:n};
    }
  };

  global.TeleportalLabels={
    LS_KEY,TP_NS,base,key,cellId,load,save,set,importAny,fromRegistry,
    normalizeBag,fromRemoteRows,autoName,Sync
  };
})(window);
