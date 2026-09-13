import {test,expect} from '@playwright/test';

test.beforeEach(async({page})=>{
  await page.route('**/v1/location/**',route=>route.fulfill({json:{city:'苏州市',note:'测试默认城市'}}));
});

test('recommendation mode defaults to best and is submitted as an edited requirement',async({page})=>{
  await page.goto('/');
  const best=page.getByRole('button',{name:/最佳机位/});
  const multiple=page.getByRole('button',{name:/多个候选/});
  await expect(best).toHaveAttribute('aria-pressed','true');
  await multiple.click();
  await expect(multiple).toHaveAttribute('aria-pressed','true');
  const requestPromise=page.waitForRequest(request=>request.url().endsWith('/v1/notebook'));
  await page.getByRole('button',{name:'发现值得拍的机位',exact:true}).click();
  const request=await requestPromise;
  const payload=request.postDataJSON();
  expect(payload.intent.recommendation_mode).toBe('multiple');
  expect(payload.edited_fields).toContain('recommendation_mode');
});

test('photography topics start empty, stay collapsed, and refresh with each description',async({page})=>{
  await page.goto('/');
  const topics=page.locator('details.category-details').first();
  await expect(topics).not.toHaveAttribute('open','');
  await topics.locator('summary').click();
  await expect(topics.getByRole('button',{name:'风光',exact:true})).toHaveAttribute('aria-pressed','false');
  await page.getByLabel('数据模式').selectOption('mock');
  await page.getByLabel('说说你的拍摄想法').fill('拍老街居民和小店，想要复古和蓝调。');
  await page.getByRole('button',{name:'发现值得拍的机位',exact:true}).click();
  let dialog=page.getByRole('dialog');
  await expect(dialog.getByText(/已从描述中识别/)).toContainText('人文');
  await expect(dialog.getByText(/已从描述中识别/)).toContainText('复古');
  await dialog.getByRole('button',{name:'关闭确认'}).click();

  await page.getByLabel('说说你的拍摄想法').fill('拍建筑线条');
  await page.getByRole('button',{name:'发现值得拍的机位',exact:true}).click();
  dialog=page.getByRole('dialog');
  const recognized=dialog.getByText(/已从描述中识别/);
  await expect(recognized).toContainText('建筑');
  await expect(recognized).not.toContainText('人文');
  await expect(recognized).not.toContainText('复古');
  const confirmTopics=dialog.locator('details.category-details');
  await confirmTopics.locator('summary').click();
  await expect(confirmTopics.getByRole('button',{name:'建筑',exact:true})).toHaveAttribute('aria-pressed','true');
  await expect(confirmTopics.getByRole('button',{name:'人文',exact:true})).toHaveAttribute('aria-pressed','false');
  await expect(dialog.getByLabel('确认结束日期')).toHaveCount(0);
});

test('an earlier end time is submitted as next-day without an end-date field',async({page})=>{
  await page.goto('/');
  await expect(page.getByLabel('拍摄日期',{exact:true})).toHaveValue(/^\d{4}-\d{2}-\d{2}$/);
  const date=await page.getByLabel('拍摄日期',{exact:true}).inputValue();
  await page.getByLabel('开始时间',{exact:true}).fill('22:00');
  await page.getByLabel('结束时间',{exact:true}).fill('01:00');
  const requestPromise=page.waitForRequest(request=>request.url().endsWith('/v1/notebook'));
  await page.getByRole('button',{name:'发现值得拍的机位',exact:true}).click();
  const payload=(await requestPromise).postDataJSON();
  const expected=new Date(`${date}T00:00:00Z`);expected.setUTCDate(expected.getUTCDate()+1);
  expect(payload.end_date).toBe(expected.toISOString().slice(0,10));
  await expect(page.getByLabel('结束日期',{exact:true})).toHaveCount(0);
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
  await page.locator('.task-details summary').first().click();
  await expect(page.locator('.task-details').first()).toContainText('缺少起点');
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
