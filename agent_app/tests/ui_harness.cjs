const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const root = path.join(__dirname, '../src/merchant_sandbox/static');

// A small DOM boundary double: replacing markup recreates form nodes, as in a browser.
function harness({storage = new Map(), transport = async () => ({}), manual = false} = {}) {
  const nodes = new Map(), requests = [], timers = [];
  function node(id) {
    if (!nodes.has(id)) {
      const el = {id, value:'', checked:false, disabled:false, hidden:false, children:[], dataset:{},
        textContent:'', setAttribute(k,v){this[k]=v;}, getAttribute(k){return this[k];},
        querySelectorAll(){return [];}, append(v){this.children.push(v);}, focus(){},
        insertAdjacentHTML(_,v){this.innerHTML = this.innerHTML + v;}};
      let markup = '';
      Object.defineProperty(el, 'innerHTML', {get:()=>markup, set:v=>{
        markup = v; el.children = [];
        for (const m of v.matchAll(/<(?:input|select|textarea|button|div)[^>]*\bid="([^"]+)"[^>]*>/g)) {
          const child = node(m[1]); child.value = m[0].match(/\bvalue="([^"]*)"/)?.[1] || '';
          child.children = []; child.disabled = /\bdisabled\b/.test(m[0]);
        }
      }});
      nodes.set(id,el);
    }
    return nodes.get(id);
  }
  let key = 0;
  const context = {console, Map, Set, URL, Blob, structuredClone, Uint8Array, btoa:v=>Buffer.from(v,'binary').toString('base64'),
    crypto:{randomUUID:()=>`ui-test-key-${++key}`},
    localStorage:{getItem:k=>storage.get(k)??null,setItem:(k,v)=>storage.set(k,v),removeItem:k=>storage.delete(k)},
    document:{getElementById:node,querySelectorAll:()=>[],createElement:()=>({}),addEventListener(){}},
    setInterval:fn=>{timers.push(fn);return timers.length;},setTimeout(){},
    fetch:async (url,options={})=>{
      const body = options.body ? JSON.parse(options.body) : undefined;
      requests.push({url,body,options});
      const out = await transport(url,body);
      return {ok:true,status:200,json:async()=>out};
    }};
  vm.createContext(context);
  if(manual) vm.runInContext(fs.readFileSync(path.join(root,'test-application.js'),'utf8'),context);
  else {
    const staff = path.join(root,'staff.js');
    const old = fs.readFileSync(path.join(root,'index.html'),'utf8').match(/<script>([\s\S]*?)<\/script>/)?.[1];
    vm.runInContext(fs.existsSync(staff)?fs.readFileSync(staff,'utf8'):old.split('(async()=>{try{config=')[0],context);
    vm.runInContext(fs.readFileSync(path.join(root,'lending.js'),'utf8'),context);
  }
  return {context,node,storage,requests,timers,run:code=>vm.runInContext(code,context),plain:v=>JSON.parse(JSON.stringify(v))};
}
module.exports = {harness};
