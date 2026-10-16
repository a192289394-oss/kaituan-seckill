// Read-only prototype calling the app's normal network executor, no WebView.
let Callback=null;let pending=null;let sequence=0;
rpc.exports.fetch=function(packetJson){return new Promise((resolve,reject)=>Java.perform(()=>{
 try{
  if(pending)throw new Error('Request already running');
  const packet=JSON.parse(packetJson);
  if(packet.method!=='GET' && !(packet.method==='POST' && /\/(list|pre_check|batch_input|get)\/?$/.test(packet.url)))throw new Error('Read-only probe');
  const token=++sequence;
  function finish(callback,result,error){
   if(!pending||Number(callback.token.value)!==pending.token)return;
   const p=pending;pending=null;clearTimeout(p.timer);
   // Return from the JNI callback before letting the host unload this script.
   setTimeout(()=>{if(error)p.reject(new Error(error));else p.resolve(result);},75);
  }
  if(!Callback)Callback=Java.registerClass({name:'cn.keyframe.FetchProbe'+Date.now(),
   implements:[Java.use('com.bytedance.ls.merchant.crossplatform_impl.method.fetch.x.b')],
   fields:{token:'int'},methods:{a:[
    {returnType:'void',argumentTypes:['java.util.Map'],implementation:function(map){
     const raw=map.get('_raw');finish(this,{raw:raw?String(raw):null,http:Number(String(map.get('_raw_status_code')))},null);
    }},
    {returnType:'void',argumentTypes:['int','java.lang.String','java.lang.Object'],implementation:function(code,msg,object){finish(this,null,'Native network error '+code);}}
   ]}});
  const callback=Callback.$new();callback.token.value=token;
  pending={token:token,resolve:resolve,reject:reject,callback:callback,
   timer:setTimeout(()=>{if(pending&&pending.token===token){pending=null;reject(new Error('Native network timeout'));}},20000)};
  const Proxy=Java.use('com.bytedance.ls.merchant.crossplatform_impl.method.fetch.x.XFetchProxy');
  const field=Proxy.class.getDeclaredField('b');field.setAccessible(true);const proxy=Java.cast(field.get(null),Proxy);
  proxy.a.overload('com.bytedance.ies.xbridge.model.a.c','org.json.JSONObject','java.lang.String',
    'com.bytedance.ls.merchant.crossplatform_impl.method.fetch.x.b').call(proxy,null,
    Java.use('org.json.JSONObject').$new(String(packetJson)),'WEB',callback);
 }catch(e){if(pending){clearTimeout(pending.timer);pending=null;}reject(new Error(String(e)));}
}));};
'';
