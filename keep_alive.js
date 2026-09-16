const puppeteer = require('puppeteer');

(async () => {
  console.log('启动防检测无头浏览器...');
  const browser = await puppeteer.launch({
    headless: true,
    args: [
      '--no-sandbox',
      '--disable-setuid-sandbox',
      '--disable-blink-features=AutomationControlled' // 绕过 Streamlit 的 Bot 检测
    ]
  });

  const page = await browser.newPage();
  await page.setViewport({ width: 1280, height: 800 });
  
  // 伪装为真实桌面 Chrome
  await page.setUserAgent('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36');

  const targetUrl = 'https://my-stock-app-nqyn5agryfl6ggzjezvvms.streamlit.app/';
  console.log(`正在访问应用: ${targetUrl}`);

  try {
    await page.goto(targetUrl, { waitUntil: 'domcontentloaded', timeout: 60000 });
    console.log('页面基础结构已加载，等待 8 秒加载动态组件...');
    await new Promise(r => setTimeout(r, 8000));

    const pageContent = await page.content();

    // 判断是否在休眠页
    if (pageContent.includes('gone to sleep') || pageContent.includes('wake it up')) {
      console.log('⚠️ 检测到 App 处于休眠状态，寻找唤醒按钮...');
      const buttons = await page.$$('button');
      let clicked = false;
      for (const btn of buttons) {
        const text = await page.evaluate(el => el.textContent, btn);
        if (text && (text.includes('Wake it up') || text.includes('Yes, wake it up'))) {
          await btn.click();
          console.log('✅ 已成功点击唤醒按钮！等待 35 秒重新编译启动...');
          clicked = true;
          await new Promise(r => setTimeout(r, 35000));
          break;
        }
      }
      if (!clicked) {
        throw new Error('未能在页面中找到“Wake it up”按钮，可能页面布局已更新');
      }
    } else {
      console.log('🎉 应用处于在线状态！开始模拟真实用户滑动以维持 WebSocket 通信...');
      // 模拟真实鼠标滚动与点击，向 Streamlit 交互通道发送数据包
      await page.evaluate(() => window.scrollBy(0, 200));
      await new Promise(r => setTimeout(r, 3000));
      await page.evaluate(() => window.scrollBy(0, -200));
      await new Promise(r => setTimeout(r, 15000));
    }

    console.log('保活任务正常完成！');
  } catch (err) {
    console.error('❌ 保活失败:', err.message);
    process.exit(1); // 触发真正的失败状态，让 Actions 产生红叉提醒
  } finally {
    await browser.close();
  }
})();
