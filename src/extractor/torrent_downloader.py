from utils import Downloader, clean_title
import constants, os, downloader
from size import Size
try:
    import torrent
except Exception as e:
    torrent = None
from timee import sleep
from translator import tr_
import utils
import filesize as fs
from datetime import datetime
import errors
TIMEOUT = 600
CACHE_INFO = True
    

@Downloader.register
class Downloader_torrent(Downloader):
    type = 'torrent'
    URLS = [r'regex:^magnet:', r'regex:\.torrent$']
    single = True
    update_filesize = False
    _info = None
    _name = None
    _filesize_prev = 0
    _upload_prev = 0
    _state = None
    _h = None
    _dn = None
    MAX_PARALLEL = 14
    skip_convert_imgs = True
    _filesize_init = False

    def init(self):
        global torrent
        if torrent is None:
            import torrent
        self.cw.pbar.hide()

    @classmethod
    def key_id(cls, url):
        id_, e = torrent.key_id(url)
        if e:
            print(e)
        return id_

    @property
    def name(self):
        if self._name is None:
            self._name = clean_title(self._info.name())
        return self._name

    def read(self):
        cw = self.cw
        title = self.url
        if self.url.startswith('magnet:'):
            qs = utils.query_url(self.url)
            if 'dn' in qs:
                self._dn = qs['dn'][0]
        info = getattr(cw, 'info?', None)
        if info is not None:
            self.print_('cached info')
            self._info = info
        if self._info is None:
            try:
                self._info = torrent.get_info(self.url, cw, timeout=TIMEOUT, callback=self.callback)
                if CACHE_INFO:
                    setattr(cw, 'info?', self._info)
            except Exception as e:
                self.update_pause()
                if not cw.paused:
                    raise errors.Invalid('Faild to read metadata: {}'.format(self.url), fail=True)
        if self._info is None:
            cw.paused = True
        if cw.paused:
            return
        hash_ = self._info.hash.hex()
        self.print_('v2: {}'.format(self._info.v2))
        self.print_('Hash: {}'.format(hash_))
        if not self._info.v2:
            self.url = 'magnet:?xt=urn:btih:{}'.format(hash_)#
        date = datetime.fromtimestamp(self._info.creation_date())
        date = date.strftime('%y-%m-%d %H:%M:%S')
        self.print_('Created on: {}'.format(date))
        self.print_('Total size: {}'.format(fs.size(self._info.total_size())))
        self.print_('Pieces: {} x {}'.format(self._info.num_pieces(), fs.size(self._info.piece_length())))
        self.print_('Creator: {}'.format(self._info.creator()))
        self.print_('Comment: {}'.format(self._info.comment()))
        cw.setTotalFileSize(self._info.total_size())
        
        cw.imgs.clear()
        cw.dones.clear()

        self.urls = [self.url]
        self.title = self.name
        self.update_files()
        
        cw.pbar.show()

    def update_files(self):
        cw = self.cw
        files = torrent.get_files(self._info, cw=cw)
        if not files:
            raise Exception('No files')
        cw.single = self.single = len(files) <= 1
        for file in files:
            filename = os.path.join(self.dir, file)
            cw.imgs.append(filename)

    def update_pause(self):
        cw = self.cw
        if cw.pause_lock:
            cw.pause_data = {
                'type': self.type,
                'url': self.url,
                }
            cw.paused = True
            cw.pause_lock = False
            self.update_tools_buttons()

    def start_(self):
        cw = self.cw
        cw.pbar.setFormat('%p%')
        cw.setColor('reading')
        cw.downloader_pausable = True
        if cw.paused:
            data = cw.pause_data
            cw.paused = False
            cw.pause_lock = False
            self.update_tools_buttons()
        self.read()
        if self.status == 'stop':
            self.stop()
            return True
        if cw.paused:
            pass
        else:
            cw.dir = self.dir
            cw.urls[:] = self.urls
            cw.clearPieces()
            self.size = Size()
            self.size_upload = Size()
            cw.pbar.setMaximum(self._info.total_size())
            cw.setColor('downloading')
            torrent.download(self._info, save_path=self.dir, callback=self.callback)
            cw.setSpeed(0.0)
            cw.setUploadSpeed(0.0)
        if not cw.alive:
            return
        self.update_pause()
        if cw.paused:
            return True
        self.title = self.name
        if not self.single:
            cw.pbar.setMaximum(len(cw.imgs))
        cw.clearPieces()
        self._h = None

    def _updateIcon(self):
        cw = self.cw
        n = 4
        for try_ in range(n):
            if cw.setIcon(cw.imgs[0], icon=try_==n-1):
                break
            sleep(.5)

    def callback(self, h, s, alerts):
        try:
            return self._callback(h, s, alerts)
        except Exception as e:
            self.print_error(e)
            return 'abort'

    def _callback(self, h, s, alerts):
        self._h = h
        cw = self.cw
            
        if self._state != s.state_str:
            self._state = s.state_str
            self.print_('state: {}'.format(s.state_str))

##        for alert in alerts:
##            self.print_('⚠️ {}'.format(alert))

        title = (self._dn or self.url) if self._info is None else self.name

        if cw.alive and cw.valid and not cw.pause_lock:
            if self._info is not None:
                if not cw.imgs: #???
                    self.print_('???')
                    self.update_files()
            
                sizes = torrent.get_file_progress(h, self._info)
                for i, (file, size) in enumerate(zip(cw.names, sizes)):
                    file = os.path.realpath(file.replace('\\\\?\\', ''))
                    if file in cw.dones:
                        continue
                    if size[0] == size[1]:
                        cw.dones.add(file)
                        file = constants.compact(file).replace('\\', '/')
                        files = file.split('/')
                        file = ' / '.join(files[1:])
                        msg = 'Completed: {}'.format(file)
                        self.print_(msg)
                        if i == 0:
                            self._updateIcon()

                cw.setPieces(torrent.pieces(h, self._info))

            filesize = s.total_done
            upload = s.total_upload
            if s.state_str in ('downloading', ):
                # init filesize
                if not self._filesize_init:
                    self._filesize_prev = filesize
                    self._filesize_init = True
                    self.print_('init filesize: {}'.format(fs.size(filesize)))
                    
                # download
                d_size = filesize - self._filesize_prev
                self._filesize_prev = filesize
                self.size += d_size
                downloader.total_download_size_torrent += d_size
                # upload
                d_size = upload - self._upload_prev
                self._upload_prev = upload
                self.size_upload += d_size
                downloader.total_upload_size_torrent += d_size
            if self._info is not None:
                cw.pbar.setValue(s.progress * self._info.total_size())
            if s.state_str == 'queued':
                title_ = 'Waiting... {}'.format(title)
            elif s.state_str == 'checking files':
                title_ = 'Checking files... {}'.format(title)
                self._filesize_prev = filesize
            elif s.state_str == 'downloading':
                title_ = '{}    (s: {}, p: {}, a:{:.3f})'.format(title, s.num_seeds, s.num_peers, s.distributed_copies)
                cw.setFileSize(filesize)
                cw.setSpeed(self.size.speed)
                cw.setUploadSpeed(self.size_upload.speed)
            elif s.state_str == 'seeding':
                title_ = '{}'.format(title)
                cw.setFileSize(filesize)
            elif s.state_str == 'reading':
                title_ = 'Reading... {}'.format(title)
            else:
                title_ = '{}... {}'.format(s.state_str.capitalize(), title)
            cw.setTitle(title_, update_filter=False)
        else:
            return 'abort'
