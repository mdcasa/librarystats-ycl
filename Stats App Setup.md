Stats App Setup



Gitbhub 

martin.house@yclibrary.org

mhouse-ycl







CNAME 

@

vnep1jmf.up.railway.app





TXT

\_railway-verify

**railway-verify=3d9aa754671fd5536dbd5a46fd2d1d66d0a8767f6bfc3ef53eef8c5c008a64c2**















Domain name:

YCLSTATS.ORG

Registry Domain ID:

Registrar WHOIS Server:

whois.cloudflare.com

Registrar URL:

https://www.cloudflare.com/

Updated Date:

2026-04-27T18:14:18Z

View more



supabase-database password

Baxter-YCL-2057



supabase

publishable key

sb\_publishable\_mTqtiiPN1g8HxQD3F43GzQ\_naX62zwk



project url

https://pxpoysibbaxrrnqvlvaw.supabase.co





session connection string





postgresql://postgres.pxpoysibbaxrrnqvlvaw:Baxter-YCL-2057@aws-1-us-east-1.pooler.supabase.com:5432/postgres







CLI setup commands

supabase login

supabase init

supabase link --project-ref pxpoysibbaxrrnqvlvaw







copy sql data

! /usr/bin/pg\_dump                                                                                                  

&#x20; "postgresql://postgres:Baxter-YCL-2057@db.mgrpsgssmlfjccalqmri.supabase.co:5432/postgres?sslmode=require" > backup.sql 



restore

! psql "postgresql://postgres.pxpoysibbaxrrnqvlvaw:Baxter-YCL-2057@aws-1-us-east-1.pooler.supabase.com:5432/postgres" < backup.sql

