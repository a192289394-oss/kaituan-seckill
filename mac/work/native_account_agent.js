// Root-owned development agent. Never log credential values.
function inJava(fn) {
  return new Promise((resolve,reject)=>Java.perform(()=>{try {resolve(fn());}catch(e){reject(String(e));}}));
}
function service() {return Java.use('com.bytedance.ls.merchant.account_impl.LsAccountServiceImpl').$new();}
function identity() {
  const model=service().getAccountInfoModel();
  if(!model)throw new Error('No active account');
  function account(a){
    const d=a.getDetail();
    return {account_id:String(a.getAccountId()),name:String(a.getAccountName()),
      root:d?String(d.getRootLifeAccountId()):null,
      life:d?String(d.getLifeAccountId()):null,poi:String(a.getPoiId())};
  }
  return {active:account(model.getActiveMerchantAccount()),main:account(model.getActiveMerchantMainAccount()),
    group:String(model.getRootGroupId()),biz_view:String(model.getCurBizViewId())};
}
rpc.exports.identity=()=>inJava(identity);
rpc.exports.headers=()=>inJava(()=>{
  const out={};const it=service().getTokenHeader().entrySet().iterator();
  while(it.hasNext()){const e=Java.cast(it.next(),Java.use('java.util.Map$Entry'));out[String(e.getKey())]=String(e.getValue());}
  return out;
});
let captured=null;let requests=[];
rpc.exports.watchrequests=()=>inJava(()=>{
  const R=Java.use('com.bytedance.retrofit2.client.Request');
  R.getUrl.implementation=function(){
    const u=this.getUrl();
    try {if(String(u).includes('/life/')){
      const headers={};const hs=this.getHeaders();
      for(let i=0;i<hs.size();i++){const h=Java.cast(hs.get(i),Java.use('com.bytedance.retrofit2.client.Header'));headers[String(h.getName())]=String(h.getValue());}
      captured={url:String(u),headers:headers};
      requests.push(captured);if(requests.length>100)requests.shift();
    }}catch(e){captured={error:String(e)};}
    return u;
  };
  return true;
});
rpc.exports.captured=()=>captured;
rpc.exports.requests=()=>requests;
rpc.exports.debugweb=()=>new Promise((resolve,reject)=>Java.perform(()=>Java.scheduleOnMainThread(()=>{
  try{Java.use('android.webkit.WebView').setWebContentsDebuggingEnabled(true);resolve(true);}catch(e){reject(String(e));}
})));
rpc.exports.switchaccount=function(account,root) {
  return new Promise((resolve,reject)=>Java.perform(()=>{
    const timeout=setTimeout(()=>reject(new Error('Native switch callback timeout; read identity before retry')),20000);
    try {
      const Callback=Java.registerClass({name:'cn.keyframe.AccountCallback'+Date.now(),
        superClass:Java.use('com.bytedance.ls.merchant.utils.framework.operate.a'),
        methods:{a:[
          {returnType:'void',argumentTypes:['java.lang.Object'],implementation:function(data){clearTimeout(timeout);resolve({ok:true,identity:identity()});}},
          {returnType:'void',argumentTypes:['com.bytedance.ls.merchant.utils.framework.operate.result.error.a'],implementation:function(error){clearTimeout(timeout);resolve({ok:false,error_class:String(error.getClass().getName())});}}
        ]}});
      const callback=Callback.$new();
      service().changeMerchantAccount(String(account),false,String(root),'kaituan_native',callback);
    }catch(e){clearTimeout(timeout);reject(String(e));}
  }));
};
rpc.exports.switchgroup=function(modelJson) {
 return new Promise((resolve,reject)=>Java.perform(()=>Java.scheduleOnMainThread(()=>{
  try {
   const Gson=Java.use('com.google.gson.Gson');
   const Model=Java.use('com.bytedance.ls.merchant.model.account.MerchantAccountModel');
   const model=Java.cast(Gson.$new().fromJson(String(modelJson),Model.class),Model);
   const thread=Java.use('android.app.ActivityThread').currentActivityThread();
   const it=thread.mActivities.value.values().iterator();let activity=null;
   while(it.hasNext()){
    const rec=Java.cast(it.next(),Java.use('android.app.ActivityThread$ActivityClientRecord'));
    if(!rec.paused.value){activity=rec.activity.value;break;}
   }
   if(!activity)throw new Error('No resumed activity');
   service().requestMerchantAccountAndChooseAutoTest(activity,model,null);
   resolve({started:true});
  }catch(e){reject(String(e));}
 })));
};
