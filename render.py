"""Render approved Hebrew copy, with visible content on every video frame."""
from pathlib import Path
import subprocess
from PIL import Image, ImageDraw, ImageFont, features
from bidi.algorithm import get_display

NAVY='#102F4D'
MINT='#60DFCE'
WHITE='#F0F7F8'
RAQM=features.check('raqm')


def width(draw,text,font):
    return draw.textlength(text if RAQM else get_display(text),font=font,**({'direction':'rtl'} if RAQM else {}))


def rtl(draw,xy,text,font,fill):
    draw.text(xy,text if RAQM else get_display(text),font=font,anchor='rt',fill=fill,**({'direction':'rtl'} if RAQM else {}))


def lines(draw, text, font, max_width):
    words = text.split(); result=[]; line=''
    for word in words:
        candidate=(line+' '+word).strip()
        if width(draw,candidate,font) > max_width:
            if not line or width(draw,word,font) > max_width:
                raise ValueError('Word exceeds slide width')
            result.append(line); line=word
        else: line=candidate
    if line: result.append(line)
    return result


def render(source, destination):
    kind=source['format']; slides=source['slides']
    if kind == 'image' and len(slides)!=1 or kind == 'carousel' and not 2<=len(slides)<=10 or kind == 'reel' and not 5<=len(slides)<=6:
        raise ValueError('Unexpected slide count')
    if kind not in ('image','carousel','reel'): raise ValueError('Unknown format')
    destination.mkdir(parents=True,exist_ok=True)
    height=1920 if kind=='reel' else 1350
    fonts=Path(__file__).parent/'assets'
    title=ImageFont.truetype(str(fonts/'Heebo-Bold.ttf'),86)
    body=ImageFont.truetype(str(fonts/'Heebo-Regular.ttf'),47)
    small=ImageFont.truetype(str(fonts/'Heebo-Regular.ttf'),29)
    images=[]
    for i,slide in enumerate(slides):
        im=Image.new('RGB',(1080,height),NAVY);d=ImageDraw.Draw(im)
        d.rounded_rectangle((70,85,1010,94),radius=4,fill=MINT)
        rtl(d,(1010,140),'משכנת׳ס',body,MINT)
        d.text((70,145),f'{i+1:02d} / {len(slides):02d}',font=small,fill=WHITE)
        y=300 if kind=='reel' else 260
        title_lines=lines(d,slide['title'],title,910)
        if len(title_lines)>3: raise ValueError('Slide title too long')
        for line in title_lines:
            rtl(d,(1000,y),line,title,WHITE);y+=112
        y+=55
        paragraphs=slide['body'].split('\n')
        for paragraph in paragraphs:
            for line in lines(d,paragraph,body,870):
                if y+70>height-230: raise ValueError('Slide copy overflows safe area')
                rtl(d,(990,y),line,body,WHITE);y+=69
            y+=28
        d.line((70,height-170,1010,height-170),fill=MINT,width=2)
        rtl(d,(1010,height-128),'אלירן שלומוב | ייעוץ משכנתאות',small,WHITE)
        path=destination/f'slide-{i+1:02d}.jpg';im.save(path,quality=94,subsampling=0);images.append(path)
    if kind!='reel': return images
    # One complete card from the first frame; no blank intro or transition frames.
    listing=destination/'frames.txt'
    listing.write_text(''.join("file '"+p.resolve().as_posix()+"'\nduration 6\n" for p in images)+"file '"+images[-1].resolve().as_posix()+"'\n")
    video=destination/'reel.mp4'
    subprocess.run(['ffmpeg','-y','-v','error','-f','concat','-safe','0','-i',str(listing),
        '-f','lavfi','-i','anullsrc=r=48000:cl=stereo','-t',str(6*len(images)),
        '-c:v','libx264','-preset','medium','-crf','23','-pix_fmt','yuv420p','-r','30',
        '-c:a','aac','-b:a','96k','-movflags','+faststart',str(video)],check=True)
    return [video]
