// Read-only, synchronous native Retrofit. No generated Java callback classes.
function singleton(name){const C=Java.use(name);const f=C.class.getDeclaredField('b');f.setAccessible(true);return Java.cast(f.get(null),C);}
function stringMap(object){const map=Java.use('java.util.LinkedHashMap').$new();for(const key of Object.keys(object||{}))map.put(key,String(object[key]));return map;}
rpc.exports.fetch=function(packetJson){return new Promise((resolve,reject)=>Java.perform(()=>{
 try{
  const p=JSON.parse(packetJson);
  if(!p.url.startsWith('https://life.douyin.com/'))throw new Error('Unexpected host');
  if(p.method!=='GET' && !(p.method==='POST' && /\/(list|pre_check|batch_input|get)\/?$/.test(p.url)))throw new Error('Read-only probe');
  const net=singleton('com.bytedance.ls.merchant.netrequest.c');
  const extra=singleton('com.bytedance.ls.merchant.netrequest.f').a();
  const headers=stringMap(p.header);const query=stringMap(p.params);
  let response;
  if(p.method==='GET')response=net.a.overload('java.lang.String','java.util.Map','java.util.Map','int','boolean','java.lang.Object').call(net,p.url,headers,query,10485760,true,extra);
  else{
   const bytes=Java.use('java.lang.String').$new(JSON.stringify(p.data||{})).getBytes('UTF-8');
   const body=Java.use('com.bytedance.retrofit2.mime.TypedByteArray').$new('application/json',bytes,Java.array('java.lang.String',[]));
   response=net.a.overload('java.lang.String','java.util.Map','java.util.Map','com.bytedance.retrofit2.mime.TypedOutput','int','boolean','java.lang.Object').call(net,p.url,headers,query,body,10485760,true,extra);
  }
  resolve({http:response.code(),raw:String(response.body())});
 }catch(e){reject(new Error(String(e)));}
}));};
