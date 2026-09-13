const puppeteer = require('puppeteer');

(async () => {
  console.log('启动无头浏览器...');
  const browser = await puppeteer.launch({
    headless: true,
    args: ['--no-sandbox', '--disable-setuid-sandbox']
  });

  const page = await browser.newPage();
  await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36');

  const targetUrl = 'https://my-stock-app-nqyn5agryfl6ggzjezvvms.streamlit.app/';
  console.log(`正在访问应用: ${targetUrl}`);

  try {
    await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 60000 });
    console.log('页面基础结构已加载，等待 10 秒确保动态组件渲染...');
    
    // 增加等待时间至 10 秒，确保休眠提示和按钮完全渲染
    await new Promise(r => setTimeout(r, 10000));

    // 检查是否有休眠唤醒按钮
    const buttons = await page.$$('button');
    let clicked = false;
    for (const button of buttons) {
      const text = await page.evaluate(el => el.textContent, button);
      if (text && (text.includes('Wake it up') || text.includes('Yes, wake it up'))) {
        console.log('检测到应用休眠，正在自动点击唤醒按钮...');
        await button.click();
        clicked = true;
        // 点击唤醒后保持页面打开 30 秒，等待 Streamlit 重新 Boot 启动
        console.log('已点击唤醒，等待 30 秒以完成部署激活...');
        await new Promise(r => setTimeout(r, 30000));
        break;
      }
    }

    if (!clicked) {
      console.log('应用已处于在线活跃状态，保持连接 20 秒维持 WebSocket...');
      await new Promise(r => setTimeout(r, 20000));
    }

    console.log('保活任务顺利完成！');
  } catch (err) {
    console.error('运行过程异常:', err.message);
  } finally {
    await browser.close();
  }
})();
