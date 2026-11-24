-- TB_법령수집실패 : 본문 수집(law_detail)에 실패한 법령 (law_enfc_id 당 1행)
--   다음 수집에서 성공하면 삭제, 계속 실패하면 최종실패일자(clct_ymd)·오류만 갱신
--   최초 실패 = inpt_dt / 최종 실패 = clct_ymd, chg_dt
--   full 적재 : 이번에 실패하지 않은 건 전부 삭제 (성공 또는 API 목록에서 없어짐)
--   incr 적재 : 이번에 성공한 건만 삭제
CREATE TABLE tb_law_clct_fail (
    law_enfc_id   varchar(20)  NOT NULL,
    clct_ymd      varchar(10)  NOT NULL,
    clct_dvs_nm   varchar(10)  NOT NULL,
    law_seq       int4         NULL,
    enfc_ymd      varchar(10)  NULL,
    law_id        varchar(20)  NULL,
    law_kor_nm    varchar      NULL,
    url_path_nm   varchar      NOT NULL,
    err_nm        varchar(100) NULL,
    err_ctxt      text         NULL,
    inpt_pgm_id   varchar(20)  NOT NULL,
    inpt_dt       timestamp    NOT NULL DEFAULT now(),
    chg_pgm_id    varchar(20)  NOT NULL,
    chg_dt        timestamp    NOT NULL DEFAULT now(),
    CONSTRAINT pk_tb_law_clct_fail PRIMARY KEY (law_enfc_id)
);

COMMENT ON TABLE  tb_law_clct_fail              IS 'TB_법령수집실패';
COMMENT ON COLUMN tb_law_clct_fail.law_enfc_id  IS '법령시행아이디';
COMMENT ON COLUMN tb_law_clct_fail.clct_ymd     IS '최종실패수집일자 (실행일, CSV 날짜폴더)';
COMMENT ON COLUMN tb_law_clct_fail.clct_dvs_nm  IS '최종실패수집구분명 (full: 전체 / incr: 증분)';
COMMENT ON COLUMN tb_law_clct_fail.law_seq      IS '법령일련번호';
COMMENT ON COLUMN tb_law_clct_fail.enfc_ymd     IS '시행일자';
COMMENT ON COLUMN tb_law_clct_fail.law_id       IS '법령아이디';
COMMENT ON COLUMN tb_law_clct_fail.law_kor_nm   IS '법령한글명';
COMMENT ON COLUMN tb_law_clct_fail.url_path_nm  IS 'URL경로명 (본문 호출 URL)';
COMMENT ON COLUMN tb_law_clct_fail.err_nm       IS '오류명 (최종 실패 시 예외 종류)';
COMMENT ON COLUMN tb_law_clct_fail.err_ctxt     IS '오류내용 (최종 실패 시)';
COMMENT ON COLUMN tb_law_clct_fail.inpt_pgm_id  IS '입력프로그램아이디';
COMMENT ON COLUMN tb_law_clct_fail.inpt_dt      IS '입력일시 (최초 실패)';
COMMENT ON COLUMN tb_law_clct_fail.chg_pgm_id   IS '변경프로그램아이디';
COMMENT ON COLUMN tb_law_clct_fail.chg_dt       IS '변경일시 (최종 실패)';
