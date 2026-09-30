import {registerHooks} from 'node:module';
registerHooks({resolve(specifier,context,nextResolve){
  if(specifier==='@whiskeysockets/baileys' && context.parentURL?.endsWith('/whatsapp/server.mjs'))
    return {url:new URL('./whatsapp-test-socket.mjs',import.meta.url).href,shortCircuit:true};
  return nextResolve(specifier,context);
}});
