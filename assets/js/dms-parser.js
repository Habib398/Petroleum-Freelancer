function dmsToDecimal(deg, min, sec, dir) {
  let dec = Number(deg) + Number(min)/60 + Number(sec)/3600;
  if (dir === 'S' || dir === 'W') dec *= -1;
  return dec;
}
function parseDMS(input){
  const r = /(\d+)°(\d+)'([\d.]+)\"?([NSEW])/g;
  let m, vals=[];
  while((m=r.exec(input))!==null){
    vals.push(dmsToDecimal(m[1], m[2], m[3], m[4]));
  }
  return {lat: vals[0], lng: vals[1]};
}