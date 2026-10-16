// App's synchronous network manager. No WebView or generated callback class.
function nativeSingleton(name){
 const C=Java.use(name);const f=C.class.getDeclaredField('b');f.setAccessible(true);return Java.cast(f.get(null),C);
}
function nativeStringMap(object){
 const map=Java.use('java.util.LinkedHashMap').$new();
 for(const key of Object.keys(object||{})){
  const value=object[key];map.put(key,typeof value==='object'?JSON.stringify(value):String(value));
 }
 return map;
}
const nativeReads={
 '/life/gate/v1/account/groupAccountList/':'GET',
 '/life/gate/v1/account/poiAccountList/':'GET',
 '/life/alliance/v1/merchant/task/product/search/':'GET',
 '/life/alliance/v1/merchant/task/detail/get/':'GET',
 '/life/alliance/v2/merchant/task/detail/get/':'GET',
 '/life/alliance/v1/merchant/partner/permission/check/':'GET',
 '/life/alliance/v1/merchant/task/marketing/activity/get/':'POST',
 '/life/marketing/v1/minus_activity/list':'POST',
 '/life/marketing/v1/minus_activity/info':'GET',
 '/life/marketing/v1/marketing/account/product/list':'GET',
 '/life/marketing/v1/minus_activity/pre_check':'POST',
 '/life/hermes/marketing_tool/live/douyin_id/batch_input':'POST'
};
const nativeWrites={
 '/life/marketing/v1/minus_activity/save':'POST',
 '/life/alliance/v1/merchant/broker/operation/confirm/':'POST'
};
function nativeFetch(packetJson,write){return new Promise((resolve,reject)=>Java.perform(()=>{
 try{
  const p=JSON.parse(packetJson);const path=p.url.slice('https://life.douyin.com'.length);
  if(!p.url.startsWith('https://life.douyin.com/') || (write?nativeWrites:nativeReads)[path]!==p.method)
   throw new Error('Unapproved native request path');
  const net=nativeSingleton('com.bytedance.ls.merchant.netrequest.c');
  const catalog=path==='/life/gate/v1/account/groupAccountList/' || path==='/life/gate/v1/account/poiAccountList/';
  // AccountRequester uses ExtraInfo(enableLsmCommonParam=false), not the
  // business-request context. Otherwise the current group overwrites groupId
  // and a different company's directory is returned during cross-group lookup.
  const extra=catalog?Java.use('java.lang.String').$new(String(Java.use('com.bytedance.ls.merchant.model.account.m').$new(false).b()))
    :nativeSingleton('com.bytedance.ls.merchant.netrequest.f').a();
  if(catalog)p.header=Object.assign({},p.header,{'agw-js-conv':'str'});
  const headers=nativeStringMap(p.header);const query=nativeStringMap(p.params);
  let response;
  if(p.method==='GET')response=net.a.overload('java.lang.String','java.util.Map','java.util.Map','int','boolean','java.lang.Object')
    .call(net,p.url,headers,query,10485760,true,extra);
  else{
   const bytes=Java.use('java.lang.String').$new(JSON.stringify(p.data||{})).getBytes('UTF-8');
   const body=Java.use('com.bytedance.retrofit2.mime.TypedByteArray').$new('application/json',bytes,Java.array('java.lang.String',[]));
   response=net.a.overload('java.lang.String','java.util.Map','java.util.Map','com.bytedance.retrofit2.mime.TypedOutput','int','boolean','java.lang.Object')
    .call(net,p.url,headers,query,body,10485760,true,extra);
  }
  resolve({http:response.code(),raw:String(response.body())});
 }catch(e){reject(new Error(String(e)));}
}));}
rpc.exports.read=packet=>nativeFetch(packet,false);
rpc.exports.dispatch=packet=>nativeFetch(packet,true);
