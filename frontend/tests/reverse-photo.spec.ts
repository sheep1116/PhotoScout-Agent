import {test,expect} from '@playwright/test';
const png=Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII=','base64');
test('reference photo upload, candidate confirmation, single-date advice and deletion',async({page})=>{
  await page.route('**/v1/location/**',route=>route.fulfill({json:{city:'南京市',note:'测试城市'}}));
  await page.goto('/');
  await page.getByRole('button',{name:'紫金山的光与影 南京 · 旅行人像'}).click();
  await page.locator('.reference-entry>summary').click();
  await page.getByLabel('上传参考照片',{exact:true}).setInputFiles({name:'reference.png',mimeType:'image/png',buffer:png});
  await expect(page.getByAltText('你上传的参考照片')).toBeVisible();
  const sent=page.waitForRequest(r=>r.url().endsWith('/analysis')&&r.method()==='POST');
  await page.getByRole('button',{name:'分析画面并寻找机位',exact:true}).click();
  expect(Object.keys((await sent).postDataJSON()).sort()).toEqual(['data_mode','notes','region_hint']);
  await expect(page.locator('.reference-choice')).toHaveCount(3);
  await expect(page.locator('.reference-observations')).toContainText('离线示例');
  await expect(page.getByLabel('比较未来天数')).toHaveCount(0);
  await expect(page.getByLabel('复刻目标')).toHaveCount(0);
  await expect(page.getByRole('button',{name:'生成该机位的复刻建议'})).toHaveCount(0);
  await page.getByRole('button',{name:'确认这是原机位'}).first().click();
  await page.getByRole('button',{name:'生成该机位的复刻建议'}).click();
  await expect(page.getByRole('heading',{name:'如何拍出同款',exact:true})).toBeVisible({timeout:30000});
  await expect(page.locator('.recreation-windows article')).toHaveCount(1);
  await expect(page.locator('.task-card')).toHaveCount(1);
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
  await page.screenshot({path:'test-results/reverse-mobile.png',fullPage:true});
  await page.getByRole('button',{name:'删除参考图',exact:true}).click();
  await expect(page.getByAltText('你上传的参考照片')).toHaveCount(0);
});

test('unmapped original hypothesis stays visible and cannot generate invented-coordinate advice',async({page})=>{
  await page.route('**/v1/location/**',route=>route.fulfill({json:{city:'南京市',note:'测试城市'}}));
  await page.route('**/v1/reference-photos',route=>route.fulfill({json:{id:'test-photo',note:'测试预览'}}));
  await page.route('**/v1/reference-photos/test-photo/analysis',route=>route.fulfill({json:{research_id:'test-analysis'}}));
  await page.route('**/v1/photo-research/test-analysis',route=>route.fulfill({json:{status:'complete',events:[]}}));
  await page.route('**/v1/reference-analyses/test-analysis',route=>route.fulfill({json:{
    id:'test-analysis',photo_id:'test-photo',data_mode:'live',exif:{},spots:[],warnings:[],sources:[],
    visual:{summary:'模型推断一段城墙',subjects:[],styles:[],composition:'城墙与地标相叠',direction:'未知',light:'any',weather:'unknown',season:'未知',focal_tendency:'unknown',long_exposure:null,hypotheses:[]},
    candidates:[{id:'guess',name:'解放门城墙段',city:'南京市',spot_id:null,status:'possible',score:45,camera_instruction:'城墙步道',reason:'地标位置相符',support:[],missing:['地图尚未唯一匹配'],conflicts:[],geometry:[],source_ids:[],verification_scope:'未经原片身份鉴定'}]
  }}));
  await page.goto('/');
  await page.locator('.reference-entry>summary').click();
  await page.getByLabel('上传参考照片',{exact:true}).setInputFiles({name:'test.png',mimeType:'image/png',buffer:png});
  await page.getByRole('button',{name:'分析画面并寻找机位',exact:true}).click();
  await expect(page.locator('.reference-choice')).toContainText('可能机位');
  await page.getByRole('button',{name:'确认这是原机位'}).click();
  await expect(page.getByRole('button',{name:'生成该机位的复刻建议'})).toBeDisabled();
  await expect(page.getByText('暂缺定位线索。请补充可识别地标或照片出处后重试。')).toHaveCount(0);
});
