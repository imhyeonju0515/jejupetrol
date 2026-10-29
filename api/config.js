// 브라우저에 필요한 공개 설정만 내려준다. (카카오 JS 키는 도메인 제한으로 보호되는 공개용 키)
module.exports = (req, res) => {
  res.setHeader('Cache-Control', 'public, s-maxage=300');
  res.status(200).json({
    kakaoJsKey: process.env.KAKAO_JS_KEY || '',
    live: !!process.env.OPINET_API_KEY,
  });
};
