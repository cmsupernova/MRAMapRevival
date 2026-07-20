(function(global){
  'use strict';
  const LS_KEY='mra_unified_v1';

  function base(value){
    return String(value||'').replace(/^.*[\\/]/,'').replace(/\.SEC$/i,'');
  }
  function key(sectorBase,x,y){
    return base(sectorBase)+':'+Number(x)+':'+Number(y);
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
  global.TeleportalLabels={
    LS_KEY,base,key,load,save,set,importAny,fromRegistry,normalizeBag,autoName
  };
})(window);
