// Jenbao public Dashboard visitor API. No portfolio data, no IP or UA storage.
const ORIGIN="https://kevintaiwan.github.io";
const UUID=/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
function dayTaipei(){
 const p=new Intl.DateTimeFormat("en-CA",{timeZone:"Asia/Taipei",year:"numeric",month:"2-digit",day:"2-digit"}).formatToParts(new Date());
 const d=Object.fromEntries(p.map(x=>[x.type,x.value]));return d.year+"-"+d.month+"-"+d.day;
}
function response(data,status=200){
 return new Response(JSON.stringify(data),{status,headers:{"Content-Type":"application/json; charset=utf-8","Cache-Control":"no-store","Access-Control-Allow-Origin":ORIGIN,"Access-Control-Allow-Methods":"GET, POST, OPTIONS","Access-Control-Allow-Headers":"Content-Type","Vary":"Origin","X-Content-Type-Options":"nosniff"}});
}
async function digest(id){
 const bytes=await crypto.subtle.digest("SHA-256",new TextEncoder().encode(id.toLowerCase()));
 return [...new Uint8Array(bytes)].map(b=>b.toString(16).padStart(2,"0")).join("");
}
export default {async fetch(req,env){
 const url=new URL(req.url);
 if(req.headers.get("Origin")&&req.headers.get("Origin")!==ORIGIN)return response({error:"origin_not_allowed"},403);
 if(url.pathname!=="/visitors")return response({error:"not_found"},404);
 if(req.method==="OPTIONS")return new Response(null,{status:204,headers:{"Access-Control-Allow-Origin":ORIGIN,"Access-Control-Allow-Methods":"GET, POST, OPTIONS","Access-Control-Allow-Headers":"Content-Type","Access-Control-Max-Age":"600","Vary":"Origin"}});
 const day=dayTaipei();
 try{
  if(req.method==="POST"){
   if(req.headers.get("Origin")!==ORIGIN)return response({error:"origin_required"},403);
   if(!(req.headers.get("Content-Type")||"").startsWith("application/json"))return response({error:"json_required"},415);
   const body=await req.text();if(body.length>256)return response({error:"body_too_large"},413);
   let data;try{data=JSON.parse(body)}catch{return response({error:"invalid_json"},400)}
   if(!data||typeof data.id!=="string"||!UUID.test(data.id))return response({error:"invalid_id"},400);
   const hash=await digest(data.id);
   await env.DB.batch([
    env.DB.prepare("INSERT OR IGNORE INTO visitors(id_hash) VALUES (?)").bind(hash),
    env.DB.prepare("INSERT OR IGNORE INTO daily_visitors(day,id_hash) VALUES (?,?)").bind(day,hash)
   ]);
  }else if(req.method!=="GET")return response({error:"method_not_allowed"},405);
  const [daily,total]=await env.DB.batch([
   env.DB.prepare("SELECT COUNT(*) AS n FROM daily_visitors WHERE day=?").bind(day),
   env.DB.prepare("SELECT COUNT(*) AS n FROM visitors")
  ]);
  return response({version:"v4",date:day,today:daily.results[0].n,total:total.results[0].n});
 }catch{return response({error:"database_unavailable"},503)}
}};
