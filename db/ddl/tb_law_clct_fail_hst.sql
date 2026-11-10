-- TB_법령수집실패이력 (초안: 테이블·컬럼명은 DBA 확정 후 db/law_sql.py 와 함께 맞출 것)
-- 본문 수집(law_detail)에 실패한 법령을 수집일자·수집구분별로 기록. 실패한 법령은 그 회차 bas 적재에서 빠짐.
CREATE TABLE tb_law_clct_fail_hst (
    clct_fail_sn  int8         GENERATED ALWAYS AS IDENTITY NOT NULL,
    clct_ymd      varchar(10)  NOT NULL,
    clct_dvs_nm   varchar(10)  NOT NULL,
    law_enfc_id   varchar(20)  NULL,
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
    CONSTRAINT pk_tb_law_clct_fail_hst PRIMARY KEY (clct_fail_sn)
);
CREATE INDEX ix_tb_law_clct_fail_hst_01 ON tb_law_clct_fail_hst (clct_ymd, clct_dvs_nm);

COMMENT ON TABLE  tb_law_clct_fail_hst              IS 'TB_법령수집실패이력';
COMMENT ON COLUMN tb_law_clct_fail_hst.clct_fail_sn IS '수집실패일련번호';
COMMENT ON COLUMN tb_law_clct_fail_hst.clct_ymd     IS '수집일자 (실행일, CSV 날짜폴더)';
COMMENT ON COLUMN tb_law_clct_fail_hst.clct_dvs_nm  IS '수집구분명 (full: 전체 / incr: 증분)';
COMMENT ON COLUMN tb_law_clct_fail_hst.law_enfc_id  IS '법령시행아이디';
COMMENT ON COLUMN tb_law_clct_fail_hst.law_seq      IS '법령일련번호';
COMMENT ON COLUMN tb_law_clct_fail_hst.enfc_ymd     IS '시행일자';
COMMENT ON COLUMN tb_law_clct_fail_hst.law_id       IS '법령아이디';
COMMENT ON COLUMN tb_law_clct_fail_hst.law_kor_nm   IS '법령한글명';
COMMENT ON COLUMN tb_law_clct_fail_hst.url_path_nm  IS 'URL경로명 (본문 호출 URL)';
COMMENT ON COLUMN tb_law_clct_fail_hst.err_nm       IS '오류명 (예외 종류)';
COMMENT ON COLUMN tb_law_clct_fail_hst.err_ctxt     IS '오류내용';
COMMENT ON COLUMN tb_law_clct_fail_hst.inpt_pgm_id  IS '입력프로그램아이디';
COMMENT ON COLUMN tb_law_clct_fail_hst.inpt_dt      IS '입력일시';
COMMENT ON COLUMN tb_law_clct_fail_hst.chg_pgm_id   IS '변경프로그램아이디';
COMMENT ON COLUMN tb_law_clct_fail_hst.chg_dt       IS '변경일시';
