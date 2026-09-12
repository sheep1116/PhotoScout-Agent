"""Private database-backed reference images. Never serve original metadata to models."""
import hashlib
import io
import json
import math
from uuid import uuid4

from PIL import Image, ImageOps
from sqlalchemy import Column, LargeBinary, MetaData, String, Table, Text, delete, insert, select, update

MAX_BYTES = 10 * 1024 * 1024
MAX_PIXELS = 24_000_000


def decode_photo(raw):
    if not raw or len(raw) > MAX_BYTES:
        raise ValueError('图片须小于 10 MB')
    try:
        with Image.open(io.BytesIO(raw), formats=['JPEG', 'PNG', 'WEBP']) as image:
            if image.width * image.height > MAX_PIXELS or getattr(image, 'n_frames', 1) != 1:
                raise ValueError('请使用不超过 2400 万像素的静态图片')
            exif = image.getexif()
            tags = dict(exif)
            tags.update(exif.get_ifd(34665))
            metadata = {}
            names = {271:'make',272:'model',36867:'captured_at_unverified',36881:'timezone_offset',33434:'exposure_seconds',33437:'aperture',34855:'iso',37386:'focal_mm',41989:'equivalent_mm',42036:'lens'}
            for key,name in names.items():
                value=tags.get(key)
                if value is None:
                    continue
                if isinstance(value,str):
                    metadata[name]=value[:160]
                else:
                    try:
                        number=float(value)
                        if math.isfinite(number) and number > 0:
                            metadata[name]=number
                    except (TypeError,ValueError,ZeroDivisionError):
                        pass
            gps=exif.get_ifd(34853)
            if all(k in gps for k in (1,2,3,4)):
                def degrees(parts):
                    return float(parts[0])+float(parts[1])/60+float(parts[2])/3600
                try:
                    lat=degrees(gps[2])*(-1 if gps[1]=='S' else 1)
                    lon=degrees(gps[4])*(-1 if gps[3]=='W' else 1)
                    if -90<=lat<=90 and -180<=lon<=180:
                        metadata['gps']={'lat':lat,'lon':lon,'coordinate_system':'WGS84'}
                except (ValueError,TypeError,IndexError,ZeroDivisionError):
                    pass
            image=ImageOps.exif_transpose(image)
            image.thumbnail((1600,1600))
            clean=Image.new('RGB',image.size,'white')
            if 'A' in image.getbands():
                clean.paste(image,mask=image.getchannel('A'))
            else:
                clean.paste(image.convert('RGB'))
            output=io.BytesIO()
            clean.save(output,format='JPEG',quality=88)
            return output.getvalue(),{'width':clean.width,'height':clean.height,'exif':metadata,'sha256':hashlib.sha256(raw).hexdigest(), 'note':'EXIF 仅为文件记录，可能缺失或被修改；原始文件不保留。'}
    except (OSError, SyntaxError, Image.DecompressionBombError) as error:
        raise ValueError('无法读取图片，请使用 JPEG、PNG 或 WebP') from error


class ReferenceStore:
    def __init__(self,engine):
        self.engine=engine
        meta=MetaData()
        self.photos=Table('reference_photos',meta,Column('id',String,primary_key=True),Column('image',LargeBinary),Column('body',Text))
        self.analyses=Table('reference_analyses',meta,Column('id',String,primary_key=True),Column('photo_id',String,index=True),Column('body',Text))
        meta.create_all(engine)

    def upload(self,raw):
        image,body=decode_photo(raw)
        identifier=uuid4().hex
        body['id']=identifier
        with self.engine.begin() as conn:
            conn.execute(insert(self.photos).values(id=identifier,image=image,body=json.dumps(body)))
        return body

    def photo(self,identifier):
        with self.engine.connect() as conn:
            row=conn.execute(select(self.photos).where(self.photos.c.id==identifier)).mappings().first()
        if row is None:
            raise KeyError(identifier)
        return row['image'],json.loads(row['body'])

    def analysis(self,identifier):
        with self.engine.connect() as conn:
            row=conn.execute(select(self.analyses).where(self.analyses.c.id==identifier)).mappings().first()
        if row is None:
            raise KeyError(identifier)
        self.photo(row['photo_id'])
        return json.loads(row['body'])

    def previous_visual(self, photo_id, model, mode):
        with self.engine.connect() as conn:
            rows=conn.execute(select(self.analyses.c.body).where(self.analyses.c.photo_id==photo_id)).scalars().all()
        for raw in reversed(rows):
            body=json.loads(raw)
            if body.get('visual') and body.get('model')==model and body.get('data_mode')==mode and body.get('vision_version')==2:
                return body['visual']
        return None

    def save(self,identifier,photo_id,body):
        with self.engine.begin() as conn:
            if conn.execute(select(self.photos.c.id).where(self.photos.c.id==photo_id)).first() is None:
                raise KeyError(photo_id)
            if conn.execute(select(self.analyses.c.id).where(self.analyses.c.id==identifier)).first():
                conn.execute(update(self.analyses).where(self.analyses.c.id==identifier).values(body=json.dumps(body)))
            else:
                conn.execute(insert(self.analyses).values(id=identifier,photo_id=photo_id,body=json.dumps(body)))

    def delete(self,identifier):
        with self.engine.begin() as conn:
            conn.execute(delete(self.analyses).where(self.analyses.c.photo_id==identifier))
            conn.execute(delete(self.photos).where(self.photos.c.id==identifier))
