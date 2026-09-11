import {test,expect} from '@playwright/test';

test.beforeEach(async({page})=>{
  await page.route('**/v1/location/**',route=>route.fulfill({json:{city:'苏州市',note:'测试默认城市'}}));
});

test('description drives editable confirmation and preserves unmentioned times',async({page})=>{
  await page.goto('/');
  await expect(page.getByLabel('目的地',{exact:true})).toHaveValue('苏州市');
  await expect(page.getByLabel('目的地',{exact:true})).toHaveClass(/suggested-default/);
  
  await page.getByLabel('数据模式').selectOption('mock');
  await page.getByLabel('说说你的拍摄想法').fill('明天想在南京拍电影感的湖面倒影，不想走太远。');
  await page.getByRole('button',{name:'发现值得拍的机位',exact:true}).click();
  const dialog=page.getByRole('dialog');
  await expect(dialog).toContainText('电影感 / 湖面倒影');
  await expect(dialog.getByLabel('确认目的地')).toHaveValue('南京');
  await expect(dialog.getByLabel('确认开始时间')).toHaveValue('00:00:00');
  await dialog.getByLabel('确认开始时间').fill('16:00');
  await dialog.getByLabel('确认结束时间').fill('19:00');
  await dialog.getByRole('button',{name:'确认需求，开始侦察'}).click();
  await expect(page.locator('.task-card')).toHaveCount(4);
  await expect(page.locator('.candidate-alerts').first()).toContainText('缺少起点');
  await expect(page.getByText('你的拍摄方式',{exact:true})).toHaveCount(0);
  await expect(page.getByRole('button',{name:'摄影爱好者',exact:true})).toHaveCount(0);
});

test('ambiguous location asks for a choice before candidate generation',async({page})=>{
  // UI-only destination fixtures; real AMap choices are covered by live acceptance.
  await page.route('**/v1/notebook',async route=>{
    const response=await route.fetch();const book=await response.json();
    book.location_status='needs_choice';book.questions=['请选择你指的地点后继续。'];
    book.location_choices=[{id:'fixture-nj',poi_id:'fixture-nj',adcode:'320106',name:'南京鼓楼公园',city:'南京市',address:'测试地点',lat:32.06,lon:118.78,verification_token:'fixture'},
      {id:'fixture-xz',poi_id:'fixture-xz',adcode:'320302',name:'徐州鼓楼',city:'徐州市',address:'测试地点',lat:34.2,lon:117.1,verification_token:'fixture'}];
    await route.fulfill({response,json:book});
  });
  await page.goto('/');
  await page.getByRole('button',{name:'紫金山的光与影 南京 · 旅行人像'}).click();
  await page.getByRole('button',{name:'发现值得拍的机位',exact:true}).click();
  const dialog=page.getByRole('dialog');
  await expect(dialog.getByRole('button',{name:'确认需求，开始侦察'})).toBeDisabled();
  await dialog.getByRole('button',{name:/南京市 南京鼓楼公园/}).click();
  await expect(dialog).toContainText('已选：南京市 南京鼓楼公园');
  await dialog.getByRole('button',{name:'确认需求，开始侦察'}).click();
  await expect(page.locator('.task-card')).toHaveCount(4);
});
