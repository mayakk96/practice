"""Rebuild the 47 original apparel illustrations and seed catalog. No network required."""
from pathlib import Path
import json, colorsys, html
ROOT=Path(__file__).resolve().parents[1]
ASSETS=ROOT/'static/assets/products'
ASSETS.mkdir(parents=True, exist_ok=True)
# Names, categories, colorways, and USD prices are deliberately authored demo merchandise.
rows=[
('Orbit Club Tee','shirts','Lilac','#B7A1E2',38),
('Cloud Nine Hoodie','hoodies','Seafoam','#A8CBB6',84),
('Solar Shell Jacket','jackets','Apricot','#EFB394',128),
('Offbeat Tee','shirts','Butter','#EBD78A',42),
('Good Weird Tee','shirts','Rosewater','#E9ADBC',38),
('Moonbeam Tee','shirts','Chalk','#E9E5DA',36),
('Static Bloom Tee','shirts','Cornflower','#9EB9E2',42),
('Soft Signal Tee','shirts','Sage','#A6B9A1',38),
('Planet People Tee','shirts','Clementine','#EBA075',44),
('Slow Motion Tee','shirts','Ink','#444851',36),
('Cosmic Doodle Tee','shirts','Pistachio','#C4CE9D',42),
('Frequency Tee','shirts','Ice Blue','#B9D1DC',40),
('Out There Tee','shirts','Orchid','#C39CBF',38),
('Daydream Dept. Tee','shirts','Sand','#D5C2A4',42),
('Little Chaos Tee','shirts','Bubblegum','#DE90A7',40),
('Alternate Reality Tee','shirts','Oat','#E4DBBF',44),
('Happy Accident Tee','shirts','Matcha','#8CA281',38),
('Neon Nap Tee','shirts','Lemon','#D8D569',42),
('Future Friend Tee','shirts','Cloud Blue','#A8BDD0',38),
('Orbit Archive Tee','shirts','Washed Black','#555254',46),
('Zero Gravity Tee','shirts','Snow','#F0EEE5',40),
('Slow Club Hoodie','hoodies','Lilac Haze','#B5A0CD',88),
('Dream State Hoodie','hoodies','Buttercream','#DECE9A',82),
('Satellite Hoodie','hoodies','Denim Blue','#819DB5',88),
('Soft Landing Hoodie','hoodies','Pink Clay','#CDA59E',84),
('Odd Hours Hoodie','hoodies','Graphite','#53595B',92),
('Utopia Hoodie','hoodies','Pistachio','#B8C59E',88),
('Afterglow Hoodie','hoodies','Tangerine','#DE9772',86),
('Weekend Planet Hoodie','hoodies','Oat Milk','#D9D0B9',82),
('Parallel Play Hoodie','hoodies','Dusty Orchid','#B49EBA',94),
('Lucky Loop Hoodie','hoodies','Leaf','#95B29C',88),
('Cloud Collector Hoodie','hoodies','Ice','#B4C9CF',86),
('Warm Signal Hoodie','hoodies','Terracotta','#BE8270',92),
('Super Soft Hoodie','hoodies','Marshmallow','#E5DED3',84),
('Off World Hoodie','hoodies','Night Sky','#646E85',94),
('Ripple Effect Hoodie','hoodies','Watermelon','#CD98A0',90),
('Lunar Track Jacket','jackets','Lilac / Ink','#A99AC6',132),
('Orbit Utility Jacket','jackets','Sage Green','#91A88F',148),
('Daybreak Windbreaker','jackets','Lemon Ice','#DAD498',118),
('Future Field Jacket','jackets','Sandstone','#BDAE8F',142),
('Meteor Coach Jacket','jackets','Cloud Blue','#9EBCCA',124),
('Peach Fuzz Jacket','jackets','Rose / Peach','#DBA3A0',136),
('Space Walk Jacket','jackets','Charcoal','#555E64',148),
('Parallel Lines Jacket','jackets','Mint / Cream','#A8C6B7',132),
('Sundown Shell Jacket','jackets','Mango','#DEA574',128),
('First Light Jacket','jackets','Off White','#DCD9CA',138),
('Cosmic Transit Jacket','jackets','Dusty Violet','#9F91B1',144),
]
assert len(rows)==47
SOLD={6,13,20,27,34,41,46}
PARTIAL={1,4,7,9,11,14,17,21,23,25,29,32,36,38,44}
SIZES=['S','M','L','XL']
def adjust(hex_, light=0):
 r,g,b=[int(hex_[i:i+2],16)/255 for i in (1,3,5)]
 h,l,s=colorsys.rgb_to_hls(r,g,b); l=max(0,min(1,l+light))
 rgb=colorsys.hls_to_rgb(h,l,s)
 return '#'+''.join(f'{round(v*255):02x}' for v in rgb)
def graphic(kind, color, pid):
 ink=adjust(color,-.37)
 cream='#F8F5E9'
 # Every design has its own art number; use five print families with custom motifs.
 if kind%6==0:
  return f'''<g transform="translate(350 334)" fill="none" stroke="{cream}" stroke-width="4"><ellipse rx="86" ry="33" transform="rotate(-28)"/><circle r="48"/><circle cx="70" cy="-43" r="9" fill="{cream}" stroke="none"/><path d="M-3-72v-18m-9 9h18"/></g><text x="350" y="422" text-anchor="middle" fill="{cream}" font-family="Arial,sans-serif" font-size="23" font-weight="800" letter-spacing="3">ORBIT CLUB</text><text x="350" y="443" text-anchor="middle" fill="{cream}" font-family="Arial,sans-serif" font-size="8" letter-spacing="3">TAKE UP A LITTLE SPACE</text>'''
 if kind%6==1:
  return f'''<g fill="{cream}" transform="translate(350 330)"><path d="M0-61 12-20 49-42 29-8 66 5 25 19 38 57 5 34-19 65-22 25-63 32-36 1-62-27-21-20-19-61 0-34Z"/><circle r="19" fill="{color}"/><path d="M-11 3q11 12 22 0" fill="none" stroke="{cream}" stroke-width="3" stroke-linecap="round"/><circle cx="-7" cy="-4" r="2" fill="{cream}"/><circle cx="7" cy="-4" r="2" fill="{cream}"/></g><text x="350" y="425" text-anchor="middle" fill="{cream}" font-family="Arial,sans-serif" font-size="19" font-weight="800" letter-spacing="2">GOOD WEIRD.</text>'''
 if kind%6==2:
  return f'''<g fill="none" stroke="{cream}" stroke-width="6" transform="translate(350 330)"><path d="M-75 14q25-80 50 0t50 0t50 0"/><path d="M-75 38q25-80 50 0t50 0t50 0" opacity=".6"/><circle cx="51" cy="-42" r="16" fill="{cream}" stroke="none"/></g><text x="350" y="421" text-anchor="middle" fill="{cream}" font-family="Arial,sans-serif" font-size="22" font-weight="800" letter-spacing="3">SOFT SIGNAL</text>'''
 if kind%6==3:
  return f'''<text x="350" y="331" text-anchor="middle" fill="{cream}" font-family="Arial,sans-serif" font-size="52" font-weight="900" letter-spacing="-3">offbeat</text><path d="M263 348q85 32 174-2" stroke="{cream}" stroke-width="4" fill="none"/><text x="350" y="387" text-anchor="middle" fill="{ink}" font-family="Arial,sans-serif" font-size="10" letter-spacing="4">EVERY BODY. EVERY ORBIT.</text><circle cx="350" cy="414" r="10" fill="{cream}"/><path d="m344 414 4 4 8-8" stroke="{color}" stroke-width="2" fill="none"/>'''
 if kind%6==4:
  return f'''<g transform="translate(350 334)" fill="{cream}"><path d="M-58 20q-19-16-6-33 7-12 23-9 7-36 38-28 24-4 31 23 28-8 35 17 24 18 0 35z"/><circle cx="-16" cy="-1" r="4" fill="{color}"/><circle cx="17" cy="-1" r="4" fill="{color}"/><path d="M-12 13q13 13 26 0" fill="none" stroke="{color}" stroke-width="3" stroke-linecap="round"/></g><text x="350" y="412" text-anchor="middle" fill="{cream}" font-family="Arial,sans-serif" font-size="18" font-weight="800" letter-spacing="2">HEAD IN THE CLOUDS</text>'''
 return f'''<g transform="translate(350 335)" stroke="{cream}" fill="none"><path d="M-63 40 0-61 64 40z" stroke-width="4"/><circle r="39" stroke-width="3"/><path d="M-80 2H80M0-75V66" stroke-width="2"/><circle r="7" fill="{cream}" stroke="none"/></g><text x="350" y="425" text-anchor="middle" fill="{cream}" font-family="Arial,sans-serif" font-size="17" font-weight="800" letter-spacing="3">ALTERNATE REALITY</text>'''
def svg(category,color,idx,name):
 dark=adjust(color,-.18); darker=adjust(color,-.28); light=adjust(color,.1); edge=adjust(color,-.12)
 defs=f'''<defs><linearGradient id="fabric" x1="0" x2="1" y1="0" y2=".2"><stop stop-color="{dark}"/><stop offset=".2" stop-color="{color}"/><stop offset=".43" stop-color="{light}"/><stop offset=".68" stop-color="{color}"/><stop offset="1" stop-color="{dark}"/></linearGradient><linearGradient id="vertical" x2=".1" y2="1"><stop stop-color="{light}"/><stop offset=".55" stop-color="{color}"/><stop offset="1" stop-color="{dark}"/></linearGradient><linearGradient id="fold" x2="1"><stop stop-color="{dark}" stop-opacity="0"/><stop offset=".5" stop-color="{dark}" stop-opacity=".38"/><stop offset="1" stop-color="{light}" stop-opacity="0"/></linearGradient><radialGradient id="collar"><stop stop-color="{darker}"/><stop offset="1" stop-color="{dark}"/></radialGradient><filter id="shadow" x="-30%" y="-30%" width="160%" height="170%"><feDropShadow dx="0" dy="23" stdDeviation="18" flood-color="#342C42" flood-opacity=".16"/></filter><filter id="texture"><feTurbulence type="fractalNoise" baseFrequency=".75" numOctaves="2" stitchTiles="stitch" result="noise"/><feColorMatrix in="noise" type="saturate" values="0"/><feBlend in="SourceGraphic" mode="soft-light"/></filter></defs>'''
 if category=='shirts':
  shape='M280 141Q350 178 420 141L476 160 587 236 532 335 476 305 481 626Q350 645 220 626L225 305 168 335 113 236 224 160Z'
  body=f'''<path d="{shape}" fill="url(#fabric)" stroke="{edge}" stroke-width="1.5"/><path d="M280 141Q284 190 350 195Q415 189 420 141Q350 170 280 141" fill="{dark}"/><path d="M286 145Q299 182 350 183Q401 180 414 145Q350 175 286 145" fill="url(#collar)"/><path d="M280 142Q285 191 350 195Q414 191 420 142" fill="none" stroke="{light}" stroke-width="4"/><path d="M232 172Q263 224 225 305M469 172Q439 225 476 305" fill="none" stroke="{dark}" stroke-width="2" opacity=".55"/><path d="m126 236 46 87m357 0 46-87M222 615Q351 633 479 615" fill="none" stroke="{light}" stroke-width="3"/><path d="M252 230q-26 183-7 343l29 47q-19-209-22-390M445 230q22 205 11 364l-26 27q16-198 15-391" fill="url(#fold)"/><path d="M278 554q64-14 143 2" fill="none" stroke="{light}" stroke-width="3" opacity=".27"/>{graphic(idx,color,name)}<path d="M470 571h18v25h-18" fill="#F6F1E6"/><path d="M475 578h7m-7 4h7m-7 4h4" stroke="#61576F" stroke-width="1.3"/>'''
 elif category=='hoodies':
  shape='M268 218 223 229Q186 241 169 299L101 570 172 596 230 415 224 650Q349 674 477 650L470 414 527 596 599 570 532 300Q516 242 477 229L431 218Z'
  body=f'''<path d="M260 236Q215 86 349 88Q484 86 440 235L400 274H294Z" fill="url(#vertical)" stroke="{edge}" stroke-width="2"/><path d="M279 218Q260 125 350 118Q441 124 422 219L390 250H310Z" fill="url(#collar)"/><path d="{shape}" fill="url(#fabric)" stroke="{edge}" stroke-width="1.5"/><path d="M269 219Q310 267 350 272Q393 263 431 219L411 208Q373 245 350 249Q324 243 289 208Z" fill="url(#vertical)"/><path d="M224 630Q350 650 477 630L477 661Q349 680 224 661Z" fill="url(#vertical)"/><path d="m104 556 72 25-6 26-74-24zm420 25 72-25 8 27-74 24z" fill="url(#vertical)"/><g stroke="{dark}" stroke-width="1.7" fill="none" opacity=".6"><path d="M224 242Q248 316 230 415M476 242Q451 317 470 415M237 642Q350 659 465 642M122 565l42 15m374 0 42-15"/><path d="M233 638v20m9-19v22m9-21v22m9-20v21m9-20v22m9-21v22m9-21v22m9-21v23m9-22v23m9-22v23m9-22v23m9-22v23m9-22v23m9-22v23m9-22v23m9-22v23m9-22v23m9-22v23m9-22v23m9-22v23m9-23v22m9-23v22m9-23v22m9-23v22m9-23v22m9-23v22"/></g><path d="M305 255q-5 32-3 70m94-71q5 39 2 74" stroke="#F3EDE0" stroke-width="4" fill="none" stroke-linecap="round"/><rect x="298" y="321" width="8" height="13" rx="2" fill="{darker}"/><rect x="394" y="324" width="8" height="13" rx="2" fill="{darker}"/><path d="M275 479 254 548Q350 565 446 548L425 479Z" fill="url(#vertical)" stroke="{edge}" stroke-width="1.5"/><path d="m278 486-17 53m161-53 17 53" stroke="{light}" stroke-width="3" fill="none"/><path d="M215 311q-31 153-62 233m330-233q32 150 62 233" fill="none" stroke="{light}" stroke-width="9" opacity=".2"/><g transform="translate(77 65) scale(.78)">{graphic(idx,color,name)}</g><path d="M428 528h21v16h-21" fill="#F6F1E6"/><path d="M433 533h11m-11 4h7" stroke="#61576F" stroke-width="1.2"/>'''
 else:
  shape='M277 178 227 198Q197 209 181 252L98 584 168 610 234 415 224 655Q350 674 476 655L466 415 532 610 602 584 519 252Q501 210 473 198L423 178 350 215Z'
  body=f'''<path d="{shape}" fill="url(#fabric)" stroke="{edge}" stroke-width="1.5"/><path d="M277 178 293 126Q350 107 407 126L423 178 350 226Z" fill="url(#vertical)"/><path d="M293 126Q350 149 407 126L401 167 350 203 299 167Z" fill="url(#collar)"/><path d="M293 126 299 167 350 203 331 239 277 178Z" fill="{light}"/><path d="M407 126 401 167 350 203 369 239 423 178Z" fill="{color}"/><path d="M224 632Q351 650 476 632L476 659Q350 679 224 659Z" fill="url(#vertical)"/><path d="m104 566 70 27-7 24-74-24zm423 27 69-27 11 27-73 24z" fill="url(#vertical)"/><path d="M350 215v447" stroke="{darker}" stroke-width="10"/><path d="M350 215v447" stroke="#DAD9CE" stroke-width="3" stroke-dasharray="2 3"/><rect x="345" y="245" width="10" height="21" rx="3" fill="#D5D3CA"/><rect x="348" y="251" width="4" height="7" rx="1" fill="{darker}"/><path d="M249 286h71v79h-71zm130 0h71v79h-71z" fill="{dark}" opacity=".35"/><path d="M247 278h75v26h-75zm132 0h75v26h-75z" fill="url(#vertical)" stroke="{edge}" stroke-width="1.5"/><circle cx="286" cy="291" r="3.5" fill="{darker}"/><circle cx="417" cy="291" r="3.5" fill="{darker}"/><path d="m254 487 56-20m80 0 56 20" stroke="{dark}" stroke-width="10"/><path d="m254 484 56-20m80 0 56 20" stroke="{light}" stroke-width="3"/><path d="M223 213Q246 308 234 415M477 213Q454 308 466 415" stroke="{dark}" stroke-width="2" fill="none"/><path d="M214 310q-31 155-62 246m334-246q31 155 62 246" fill="none" stroke="{light}" stroke-width="8" opacity=".22"/><path d="M246 572q43-12 78-1m53 0q43-12 78 1" stroke="{light}" stroke-width="3" opacity=".25" fill="none"/><g transform="translate(268 389)"><ellipse cx="13" cy="0" rx="21" ry="8" transform="rotate(-25 13 0)" fill="none" stroke="#F6F1E6" stroke-width="2"/><circle cx="13" r="11" fill="none" stroke="#F6F1E6" stroke-width="2"/><text x="13" y="26" text-anchor="middle" font-family="Arial,sans-serif" font-size="8" letter-spacing="1" fill="#F6F1E6">ODD ORBIT</text></g><path d="M448 578h31v18h-31" fill="#F6F1E6"/><text x="463" y="590" text-anchor="middle" font-family="Arial,sans-serif" font-size="6" letter-spacing="1" fill="#61576F">ORBIT</text>'''
 return f'''<svg xmlns="http://www.w3.org/2000/svg" width="700" height="800" viewBox="0 0 700 800" role="img" aria-label="{html.escape(name)} in {html.escape(color)}"><title>{html.escape(name)} — original Odd Orbit apparel illustration</title>{defs}<g filter="url(#shadow)" transform="translate(0 7)">{body}</g></svg>'''
products=[]
for idx,(name,category,color,hex_,price) in enumerate(rows):
 slug=name.lower().replace('.','').replace(' ','-')
 stock={s:8+(idx*7+i*3)%19 for i,s in enumerate(SIZES)}
 if idx in SOLD: stock={s:0 for s in SIZES}
 elif idx in PARTIAL:
  stock[SIZES[(idx+1)%4]]=0
  if idx%3==0: stock[SIZES[(idx+2)%4]]=0
 style=['A little space for your everyday adventures.','For the wonderfully out of the ordinary.','An easy layer for your next little detour.','Good energy, easy fit, endless possibilities.'][idx%4]
 category_description={
  'shirts':'An easygoing unisex tee with a relaxed silhouette, dropped shoulders, a soft ribbed crew neck, and an original Odd Orbit front print.',
  'hoodies':'A roomy unisex hoodie with a double-layer hood, soft brushed interior, kangaroo pocket, ribbed cuffs, and an original Odd Orbit print.',
  'jackets':'A lightweight unisex zip jacket with an easy layering fit, stand collar, chest pockets, and an embroidered Odd Orbit emblem.'}[category]
 material={'shirts':'100% combed cotton · 220 gsm','hoodies':'80% cotton / 20% recycled polyester · 380 gsm','jackets':'100% recycled nylon shell · cotton-blend lining'}[category]
 badge='Sold out' if idx in SOLD else ('Bestseller' if idx in {0,1,10,25} else 'New' if idx<6 or idx in {21,36} else 'Limited' if idx in PARTIAL else '')
 p={'id':slug,'name':name,'category':category,'color':color,'hex':hex_,'price':price*100,'description':f'{style} {category_description}','material':material,'fit':'Relaxed unisex fit. Choose your usual size for an easy fit; size up for an oversized look.','badge':badge,'image':f'/static/assets/products/{slug}.svg','stock':stock}
 products.append(p)
 (ASSETS/f'{slug}.svg').write_text(svg(category,hex_,idx,name))
(ROOT/'data/catalog.json').write_text(json.dumps(products,indent=2)+'\n')
assert {c:sum(p['category']==c for p in products) for c in ('shirts','hoodies','jackets')}=={'shirts':19,'hoodies':16,'jackets':12}
assert sum(all(v==0 for v in p['stock'].values()) for p in products)==7
assert sum(any(v==0 for v in p['stock'].values()) and any(v>0 for v in p['stock'].values()) for p in products)==15
print(f'Created {len(products)} original SVG illustrations and 47-product catalog; 7 sold out, 15 partial, 25 full stock.')
