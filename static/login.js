'use strict';
const t = I18n.t;
(async()=>{
  const $=id=>document.getElementById(id);
  let setup=false;
  try{
    const response=await fetch('/api/auth/state'),state=await response.json();
    if(!state.remote){location.replace('/');return;}
    setup=state.needsSetup;
    $('setupLabel').hidden=!setup;$('setupCode').required=setup;
    if(setup){$('loginHeading').textContent=t('Create your owner account');$('loginNote').textContent=t('Find the one-time setup code in the Container Manager log. Use it here to create your account.');$('signIn').textContent=t('Create owner account');$('password').autocomplete='new-password';}
  }catch{$('loginError').textContent=t('Cannot reach the app. Reload to try again.');$('loginError').hidden=false;}
  $('loginForm').onsubmit=async event=>{
    event.preventDefault();$('signIn').disabled=true;$('loginError').hidden=true;
    try{
      const response=await fetch('/api/auth/'+(setup?'setup':'login'),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({username:$('username').value,password:$('password').value,code:$('setupCode').value})});
      const data=await response.json();if(!response.ok)throw new Error(t(data.error||'Sign-in failed.'));location.replace('/');
    }catch(error){$('loginError').textContent=t(error.message);$('loginError').hidden=false;}
    finally{$('signIn').disabled=false;}
  };
})();
