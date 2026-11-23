#include "renderer.hpp"
#include <cmath>
#include <string>
namespace {
void color(cairo_t*c,double r,double g,double b,double a=1){cairo_set_source_rgba(c,r,g,b,a);}
void rect(cairo_t*c,double x,double y,double w,double h,double r){cairo_new_sub_path(c);cairo_arc(c,x+w-r,y+r,r,-1.57,0);cairo_arc(c,x+w-r,y+h-r,r,0,1.57);cairo_arc(c,x+r,y+h-r,r,1.57,3.14);cairo_arc(c,x+r,y+r,r,3.14,4.71);cairo_close_path(c);}
void text(cairo_t*c,double x,double y,const std::string&s,double size,double r,double g,double b,bool bold=false){cairo_select_font_face(c,"DejaVu Sans",CAIRO_FONT_SLANT_NORMAL,bold?CAIRO_FONT_WEIGHT_BOLD:CAIRO_FONT_WEIGHT_NORMAL);cairo_set_font_size(c,size);color(c,r,g,b);cairo_move_to(c,x,y);cairo_show_text(c,s.c_str());}
void line(cairo_t*c,int x,int y,int x2,int y2){color(c,.18,.19,.22);cairo_set_line_width(c,1);cairo_move_to(c,x,y);cairo_line_to(c,x2,y2);cairo_stroke(c);}
void badge(cairo_t*c,int x,int y,const std::string&s){rect(c,x,y,150,26,5);color(c,.13,.14,.16);cairo_fill(c);text(c,x+12,y+17,s,10,.76,.77,.79,true);}
}
void render(cairo_t*c,int w,int h,const nori::Core& core,const std::string& net){
 color(c,.031,.035,.043);cairo_paint(c); cairo_save(c); double scale=core.settings.ui_scale/100.0; cairo_scale(c,scale,scale); w=int(w/scale); h=int(h/scale);
 if(!core.input.open()){text(c,30,45,"NORI / DEVELOPMENT HOST",12,.58,.59,.62,true);text(c,30,70,"Interface closed. Press Insert or configured key.",13,.7,.71,.73);cairo_restore(c);return;}
 int side=224; color(c,.055,.062,.075);cairo_rectangle(c,0,0,side,h);cairo_fill(c);line(c,side,0,side,h);
 text(c,28,48,"N O R I",21,.90,.91,.93,true);text(c,29,68,"GAME CORE / DEV HOST",9,.49,.52,.57,true);line(c,24,88,side-24,88);
 auto names=nori::screen_names();for(int i=0;i<(int)names.size();i++){int y=108+i*48;bool active=static_cast<int>(core.nav.current())==i;if(active){rect(c,14,y,196,38,5);color(c,.13,.14,.16);cairo_fill(c);color(c,.73,.75,.79);cairo_rectangle(c,14,y+6,2,26);cairo_fill(c);}text(c,31,y+24,names[i],13,active?.93:.58,active?.94:.60,active?.95:.64,active);}
 line(c,24,h-88,side-24,h-88);text(c,28,h-58,"INTEGRATION",9,.47,.50,.54,true);text(c,28,h-37,"Not connected",12,.75,.76,.79);
 int x=side+38;int usable=w-x-38;auto screen=core.nav.current();text(c,x,45,"N O R I  /  INDEPENDENT CORE",10,.53,.55,.60,true);text(c,x,83,names.at(static_cast<int>(screen)),27,.93,.94,.95,true);badge(c,w-199,28,net.empty()?"OFFLINE":net);line(c,x,103,w-38,103);
 if(screen==nori::Screen::Dashboard){text(c,x,145,"SYSTEM OVERVIEW",10,.52,.54,.59,true);rect(c,x,161,usable,110,7);color(c,.085,.094,.11);cairo_fill(c);text(c,x+22,193,"Two platforms. One ecosystem.",17,.91,.92,.94,true);text(c,x+22,220,"No game is connected. No game data is generated.",12,.64,.67,.71);text(c,x+22,245,"Development host / not an in-game plugin",11,.49,.52,.56);int cw=(usable-20)/2;rect(c,x,291,cw,127,7);color(c,.075,.082,.095);cairo_fill(c);rect(c,x+cw+20,291,cw,127,7);color(c,.075,.082,.095);cairo_fill(c);text(c,x+20,320,"HASSLE RP 2.0",10,.53,.55,.60,true);text(c,x+20,354,"Not Connected",17,.85,.86,.88,true);text(c,x+20,385,"Authorized SDK required",11,.56,.58,.62);text(c,x+cw+40,320,"RADMIR CRMP",10,.53,.55,.60,true);text(c,x+cw+40,354,"Not Connected",17,.85,.86,.88,true);text(c,x+cw+40,385,"Authorized SDK required",11,.56,.58,.62);
 }else if(screen==nori::Screen::License){
  auto a=core.auth();nori::AuthView v;if(a)v=a->view();else {v.state=nori::ConnectionState::Offline;v.detail="Set --backend HTTPS_URL to configure authentication.";}
  text(c,x,145,"DEVICE AUTHENTICATION",10,.52,.54,.59,true);rect(c,x,161,usable,285,7);color(c,.085,.094,.11);cairo_fill(c);
  text(c,x+22,194,nori::connection_name(v.state),18,.92,.93,.95,true);text(c,x+22,225,v.detail,11,.66,.68,.72);
  if(!v.code.empty()){text(c,x+22,264,"PAIRING CODE",10,.56,.58,.62,true);text(c,x+22,294,v.code,23,.93,.94,.96,true);text(c,x+22,322,"Expires: "+v.code_expires,11,.67,.69,.73);}
  if(v.state==nori::ConnectionState::Online){text(c,x+22,264,"Platform: "+v.platform,12,.83,.84,.86);text(c,x+22,293,"License expires: "+v.license_expires,12,.83,.84,.86);text(c,x+22,322,"Device: "+v.device_id,11,.70,.72,.75);text(c,x+22,352,"Device status: active",12,.83,.84,.86);}
  text(c,x+22,414,"Server actions remain disabled; no game is connected.",11,.53,.56,.60);
  auto button=[&](int bx,int by,int bw,const std::string& label,bool enabled){rect(c,bx,by,bw,36,5);color(c,enabled?.16:.095,enabled?.17:.10,enabled?.19:.11);cairo_fill(c);text(c,bx+12,by+23,label,11,enabled?.88:.40,enabled?.89:.42,enabled?.91:.45,true);};
  bool canpair=a&&!v.busy&&v.can_pair;button(x,470,218,"Pair Hassle",canpair);button(x+228,470,218,"Pair Radmir",canpair);
  button(x,518,158,"Confirmed",a&&!v.busy&&v.state==nori::ConnectionState::WaitingConfirmation);button(x+168,518,140,"Refresh",a&&!v.busy&&(v.state==nori::ConnectionState::Online||v.state==nori::ConnectionState::Offline||v.state==nori::ConnectionState::Denied));button(x+318,518,140,"Cancel",a&&(v.busy||v.state==nori::ConnectionState::WaitingConfirmation||v.retry_scheduled));
  text(c,x,584,"Enter the displayed code in the Telegram bot; then press Confirmed.",11,.53,.56,.60);
 }else if(screen==nori::Screen::Settings){text(c,x,143,"PREFERENCES",10,.52,.54,.59,true);rect(c,x,160,usable,255,7);color(c,.085,.094,.11);cairo_fill(c);std::string vals[]={"Toggle menu key     "+core.settings.hotkey,"Interface scale          "+std::to_string(core.settings.ui_scale)+"%",std::string("Notifications              ")+(core.settings.notifications?"On":"Off"),std::string("Reduced motion          ")+(core.settings.reduced_motion?"On":"Off"),"Reset preferences"};for(int i=0;i<5;i++){text(c,x+22,191+46*i,vals[i],13,.85,.86,.89,i==4);text(c,x+usable-90,191+46*i,i==4?"RESET":"CHANGE",10,.57,.59,.65,true);if(i<4)line(c,x+20,205+46*i,x+usable-20,205+46*i);}text(c,x,449,"Changes are saved locally. Credentials are never stored here.",11,.52,.55,.59);
 }else {auto state=core.state(screen);text(c,x,145,"STATUS",10,.52,.54,.59,true);rect(c,x,161,usable,173,7);color(c,.085,.094,.11);cairo_fill(c);text(c,x+24,201,nori::state_name(state),19,.87,.88,.90,true);std::string detail=(state==nori::ViewState::NotConnected)?"Game adapter is disabled. An authorized SDK is required.":"Backend verification is unavailable. No cached license grants access.";text(c,x+24,233,detail,12,.62,.64,.68);text(c,x+24,279,screen==nori::Screen::License?"Pairing requires the approved backend v2 protocol.":"Unavailable features do not produce simulated data.",11,.50,.52,.56);}
 text(c,x,h-35,"INSERT / configured shortcut   •   TEST HOST ONLY",10,.44,.46,.50);if(!net.empty())text(c,w-200,h-35,net,10,.55,.58,.62); cairo_restore(c);
}
