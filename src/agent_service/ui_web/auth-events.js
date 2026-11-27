"use strict";
// Same-origin sign-out signal contains no account, CSRF or session credential.
const authChannel=typeof BroadcastChannel==='function'?new BroadcastChannel('impactmap-signout'):null;
function notifySignedOut(){authChannel?.postMessage('signed-out');}
function onSignedOut(callback){authChannel?.addEventListener('message',event=>{if(event.data==='signed-out')callback();});}
