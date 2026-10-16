// App 10.6.5 account service. Native calls preserve its normal auth flow.
function runJava(fn) {
  return new Promise((resolve,reject)=>Java.perform(()=>{try{resolve(fn());}catch(e){reject(new Error(String(e)));}}));
}
function service(){return Java.use('com.bytedance.ls.merchant.account_impl.LsAccountServiceImpl').$new();}
function identity(){
  const info=service().getAccountInfoModel();
  if(!info)throw new Error('No active merchant login');
  function account(a){const d=a.getDetail();return {account_id:String(a.getAccountId()),
    name:String(a.getAccountName()),root:d?String(d.getRootLifeAccountId()):null,
    life:d?String(d.getLifeAccountId()):null,poi:String(a.getPoiId())};}
  return {active:account(info.getActiveMerchantAccount()),main:account(info.getActiveMerchantMainAccount()),
    group:String(info.getRootGroupId()),biz_view:String(info.getCurBizViewId())};
}
rpc.exports.identity=()=>runJava(identity);
rpc.exports.businessviews=()=>runJava(()=>{
 const m=service().getBizViewModel();if(!m)return {enabled:[],views:[]};
 const ids=m.enableViewIds();const enabled=[];if(ids)for(let i=0;i<ids.size();i++)enabled.push(String(ids.get(i)));
 const list=m.getBizViewList();const views=[];if(list)for(let i=0;i<list.size();i++){
  const v=Java.cast(list.get(i),Java.use('com.bytedance.ls.merchant.model.account.BizViewInfo'));
  views.push({id:String(v.getBizViewId()),name:String(v.getName()),default:v.getDefaultSelect()});
 }
 const roleIds=m.enableRoleIds();const enabledRoles=[];if(roleIds)for(let i=0;i<roleIds.size();i++)enabledRoles.push(String(roleIds.get(i)));
 const roleList=m.getBizRoleList();const roles=[];if(roleList)for(let i=0;i<roleList.size();i++){
  const r=Java.cast(roleList.get(i),Java.use('com.bytedance.ls.merchant.model.account.BizViewRoleInfo'));
  roles.push({id:String(r.getBizViewId()),name:String(r.getName()),need_poi:r.needPoiSelect()});
 }
 return {enabled:enabled,views:views,enabled_roles:enabledRoles,roles:roles};
});
rpc.exports.switchview=function(viewId){return new Promise((resolve,reject)=>Java.perform(()=>Java.scheduleOnMainThread(()=>{
 try{
  const svc=service();const m=svc.getBizViewModel();
  const enabled=m?m.enableViewIds():null;
  if(!enabled || !enabled.contains(String(viewId)))throw new Error('Business view not authorised by current app metadata');
  const list=m.getBizViewList();let chosen=null;
  for(let i=0;i<list.size();i++){
   const v=Java.cast(list.get(i),Java.use('com.bytedance.ls.merchant.model.account.BizViewInfo'));
   if(String(v.getBizViewId())===String(viewId)){if(chosen)throw new Error('Ambiguous business view');chosen=v;}
  }
  if(!chosen)throw new Error('Business view unavailable');
  // Same internal branch used by the normal changeBizView handler, after its
  // enabledViewIds check. It does not change server permissions or login data.
  const Manager=Java.use('com.bytedance.ls.merchant.account_impl.merchant.manage.biz.c');
  const f=Manager.class.getDeclaredField('b');f.setAccessible(true);const manager=Java.cast(f.get(null),Manager);
  const result=manager.a.overload('com.bytedance.ls.merchant.model.account.AccountInfoModel',
    'com.bytedance.ls.merchant.model.account.BizViewInfo','java.lang.String').call(manager,svc.getAccountInfoModel(),chosen,'select');
  resolve({result:result,identity:identity()});
 }catch(e){reject(new Error(String(e)));}
})))};
let pending=null;let Callback=null;let requestSequence=0;
rpc.exports.switchaccount=function(account,root){
 return new Promise((resolve,reject)=>Java.perform(()=>{
  if(pending){reject(new Error('Native account switch already pending'));return;}
  const token=String(++requestSequence);
  const timer=setTimeout(()=>{if(pending && pending.token===token)pending=null;reject(new Error('Native account switch timed out; inspect identity before retry'));},20000);
  pending={resolve:resolve,reject:reject,timer:timer,callback:null,token:token};
  function finish(ok,callbackToken){if(!pending || pending.token!==callbackToken)return;const p=pending;pending=null;clearTimeout(p.timer);p.resolve({ok:ok,identity:identity()});}
  try{
   if(!Callback)Callback=Java.registerClass({name:'cn.keyframe.NativeAccountCallback'+Date.now(),
    superClass:Java.use('com.bytedance.ls.merchant.utils.framework.operate.a'),fields:{requestToken:'java.lang.String'},methods:{a:[
     {returnType:'void',argumentTypes:['java.lang.Object'],implementation:function(){finish(true,String(this.requestToken.value));}},
     {returnType:'void',argumentTypes:['com.bytedance.ls.merchant.utils.framework.operate.result.error.a'],implementation:function(){finish(false,String(this.requestToken.value));}}
    ]}});
   pending.callback=Callback.$new();
   pending.callback.requestToken.value=token;
   service().changeMerchantAccount(String(account),false,String(root),'kaituan_native',pending.callback);
  }catch(e){clearTimeout(timer);pending=null;reject(new Error(String(e)));}
 }));
};
rpc.exports.switchgroup=function(modelJson){
 return new Promise((resolve,reject)=>Java.perform(()=>Java.scheduleOnMainThread(()=>{
  try{
   const Model=Java.use('com.bytedance.ls.merchant.model.account.MerchantAccountModel');
   const model=Java.cast(Java.use('com.google.gson.Gson').$new().fromJson(String(modelJson),Model.class),Model);
   const it=Java.use('android.app.ActivityThread').currentActivityThread().mActivities.value.values().iterator();
   let activity=null;
   while(it.hasNext()){
    const rec=Java.cast(it.next(),Java.use('android.app.ActivityThread$ActivityClientRecord'));
    if(!rec.paused.value){activity=rec.activity.value;break;}
   }
   if(!activity)throw new Error('No resumed merchant activity');
   service().requestMerchantAccountAndChooseAutoTest(activity,model,null);
   resolve({started:true});
  }catch(e){reject(new Error(String(e)));}
 })));
};
rpc.exports.debugweb=()=>new Promise((resolve,reject)=>Java.perform(()=>Java.scheduleOnMainThread(()=>{
 try{Java.use('android.webkit.WebView').setWebContentsDebuggingEnabled(true);resolve(true);}catch(e){reject(String(e));}
})));
