#!/usr/bin/python

"""
Usage: %s <verb> <flags>

For verb in
  edit -- edit the current change description
  show -- write to stdout the current change description in a form suitable for
          an SVN commit message.
  snapshot -- update appspot with the current change description

Flags:
  -m --message : overrides the changelist message, a one line summary.
  -d --description : overrides the changelist's detailed description.
  -r --reviewer : overrides the email of the assigned reviewer
  -c --cc : overrides the CC list.
  -i --issue : overrides the CL number.  DO NOT USE.
  --send_mail : send mail.  For snapshot only.
See (upload.py --help) for the meaning of these parameters.
"""
# TODO(mikesamuel): need a verb to set the "Fixed" bit on an issue in appspot
# when it is committed.

import commands
import os
import re
import sys
import subprocess
import tempfile
import upload

class ChangeList(object):
  def __init__(self, issue=None, description=None, reviewer=None, cc=None,
               message=None):
    """
    A value of None for any parameter means its unspecified and so will not
    be set on a merge operation.
    """
    self.issue = issue
    self.description = description
    self.cc = cc
    self.reviewer = reviewer
    self.message = message
    # TODO(mikesamuel): add a code.google.com bug number to update when code
    # is submitted

  def get_app_spot_uri(self):
    """The URL of a change list."""
    if self.issue is not None:
      return 'http://codereview.appspot.com/%d' % int(self.issue)
    return None

  def is_unspecified(self):
    return (self.issue is None and self.description is None and self.cc is None
            and self.reviewer is None and self.message is None)

  def get_upload_args(self, send_mail=False):
    """
    Returns a parameter list to update.py, the tool that is used to create or
    modify a code review.
    """
    args = []
    if self.issue:
      args.extend(['--issue', str(self.issue)])
    if self.description:
      args.extend(['--description', str(self.description)])
    args.extend(
        ['--cc',
         include_if_not_present(
             comma_separated_list=self.cc,
             to_include='google-caja-discuss@googlegroups.com')])
    if self.reviewer:
      args.extend(['--reviewer', str(self.reviewer)])
    if self.message:
      args.extend(['--message', str(self.message)])
    if send_mail:
      args.append('--send_mail')
    return args

  def merge_into(self, target):
    if self.issue is not None:        target.issue = self.issue
    if self.description is not None:  target.description = self.description
    if self.cc is not None:           target.cc = self.cc
    if self.reviewer is not None:     target.reviewer = self.reviewer
    if self.message is not None:      target.message = self.message


def include_if_not_present(comma_separated_list, to_include):
  assert ',' not in to_include
  if not comma_separated_list: return to_include
  if re.search(r'(^|,)%s(,|$)' % re.escape(to_include), comma_separated_list):
    return comma_separated_list
  else:
    return '%s,%s' % (comma_separated_list, to_include)


def editable_change(cl):
  """
  Produces a human editable file that allows the editor to change changelist
  fields.
  """
  return ('''


### Please edit the fields below, save this file, and exit your editor.
### Lines starting with ### and ending with : are treated as section headings.
### Other lines starting with ### are ignored.
### If the file is empty or the first line the changelist will not be changed.

### Issue:
%(issue)s
### URL:
%(url)s


### Message:
### One-line summary of the change.
%(message)s


### Description:
### Detailed description of the change.
%(description)s


### Reviewer:
### Email address of the code reviewer.
%(reviewer)s


### CC:
### Email addresses that should be CCed on the change.
%(cc)s


''' % pack_for_display(cl)).strip()


def readable_change(cl):
  return ('''


Issue %(issue)s  %(url)s
%(message)s

%(description)s

R=%(reviewer)s


''' % pack_for_display(cl)).strip()


def pack_for_display(changelist):
  """Converts a changelist to a hash with human readable default values."""
  return {
    'issue': changelist.issue or '<unassigned>',
    'url': changelist.get_app_spot_uri() or '<unassigned>',
    'message': changelist.message or '',
    'description': changelist.description or '',
    'reviewer': changelist.reviewer or '',
    'cc': changelist.cc or '',
  }


def parse_change(editable_change):
  """
  Parses a ChangeList from info in a file generated by editable_change().
  """

  pending_name = None
  pending = []
  fields = {}

  def commit():
    if pending_name is not None:
      body = '\n'.join(pending).strip()
      if body:
        fields[pending_name] = body

  for line in re.split(r'\r\n?|\n', editable_change):
    if line.startswith('###'):
      m = re.search(r'^\#\#\# (\w+):\s*$', line)
      if m is not None:
        commit()
        pending_name = m.group(1)
        pending = []
      continue
    pending.append(line)
  commit()

  issue = fields.get('Issue')
  if issue is not None and not re.search('^\d+$', issue):
    issue = None
  description = fields.get('Description')
  cc = fields.get('CC')
  reviewer = fields.get('Reviewer')
  message = fields.get('Message')
  return ChangeList(issue=issue, description=description, cc=cc,
                    reviewer=reviewer, message=message)


def do_edit(given_cl, current_cl, cl_file_path):
  if given_cl.is_unspecified():
    # Show an editor if CL not specified on the command-line
    tmp_fd, tmp_path = tempfile.mkstemp(prefix='appspot-', suffix='.txt')
    os.write(tmp_fd, editable_change(current_cl))
    os.close(tmp_fd)
    retcode = subprocess.call(
        '%s %s' % (os.getenv('VISUAL', os.getenv('EDITOR')),
                   commands.mkarg(tmp_path)),
        shell=True)
    try:
      if retcode < 0:
        raise Exception('editor closed with signal %s' % -retcode)
      elif retcode < 0:
        raise Exception('editor exited with error value %s' % retcode)
      edited_cl = parse_change(open(tmp_path).read())
    finally:
      os.remove(tmp_path)
    if edited_cl.is_unspecified():
      print >>sys.stderr, 'cancelled edit'
      return
    edited_cl.merge_into(current_cl)
  else:
    given_cl.merge_into(current_cl)
  out = open(cl_file_path, 'w')
  out.write(editable_change(current_cl))
  out.close()


def do_show(given_cl, current_cl):
  given_cl.merge_into(current_cl)
  print readable_change(current_cl)


def do_snapshot(given_cl, current_cl, cl_file_path, send_mail):
  if not given_cl.is_unspecified():
    given_cl.merge_into(current_cl)
    out = open(cl_file_path, 'w')
    out.write(editable_change(current_cl))
    out.close()
    send_mail = True
  # If the CL does not have an issue number, send mail since it's the first
  # upload.
  if current_cl.issue is None:
    send_mail = True
  argv = [sys.argv[0]]  # upload.RealMain expects argv[0] to be the program
  argv.extend(current_cl.get_upload_args(send_mail=send_mail))
  issue = upload.RealMain(argv)
  # If an issue number was assigned as part of the update, store that with
  # our issue record.
  if issue and str(issue) != current_cl.issue:
    do_edit(ChangeList(issue=str(issue)), current_cl, cl_file_path)


def main():
  def parse_flags(flags):
    abbrevs = {
        '-i': '--issue',
        '-m': '--message',
        '-d': '--description',
        '-r': '--reviewer',
        '-c': '--cc',
        }

    def to_pairs():
      pairs = []
      i = 0
      while i < len(flags):
        flag = flags[i]
        if flag == '--':
          i += 1
          break
        elif flag.startswith('--'):
          eq = flag.find('=')
          if eq >= 0:
            pairs.append((flag[:eq], flag[eq+1:]))
          else:
            i += 1
            pairs.append((flag, flags[i]))
        elif flag.startswith('-'):
          i += 1
          pairs.append((abbrevs[flag], flags[i]))
        else:
          break
        i += 1
      return pairs, flags[i:]
    params = {}
    pairs, argv = to_pairs()
    for key, value in pairs:
      params[key] = value
    return params, argv

  def show_help_and_exit():
    # __doc__ is the doc comment at the top of this file
    print >>sys.stderr, __doc__ % sys.argv[0]
    sys.exit(-1)

  # Parse one changelist from the parameters
  if len(sys.argv) < 2 or '-?' in sys.argv or '--help' in sys.argv:
    show_help_and_exit()
  verb = sys.argv[1]
  if verb.startswith('-'): show_help_and_exit()

  params, argv = parse_flags(sys.argv[2:])
  # TODO(mikesamuel): error out on unused params.
  if len(argv) != 0: show_help_and_exit()
  given_cl = ChangeList(
      issue=params.get('--issue'),
      message=params.get('--message'),
      description=params.get('--description'),
      reviewer=params.get('--reviewer'),
      cc=params.get('--cc'))

  # Figure out where the CL lives on disk
  client_root = os.path.abspath(os.curdir)
  while client_root and os.path.basename(client_root) != 'google-caja':
    client_root = os.path.dirname(client_root)
  if not client_root:
    print >>sys.stderr, '''Cannot locate client root.
No directory named google-caja on %s''' % os.path.abspath(os.curdir)
    sys.exit(-1)
  cl_file_path = os.path.join(client_root, '.appspot-change')

  # Load any existing changelist
  if os.path.isfile(cl_file_path):
    print >>sys.stderr, 'reading from %s' % cl_file_path
    current_cl = parse_change(open(cl_file_path).read())
  else:
    current_cl = ChangeList()

  if verb == 'edit':
    do_edit(given_cl=given_cl, current_cl=current_cl, cl_file_path=cl_file_path)
  elif verb == 'show':
    do_show(given_cl=given_cl, current_cl=current_cl)
  elif verb == 'snapshot':
    do_snapshot(
        given_cl=given_cl, current_cl=current_cl, cl_file_path=cl_file_path,
        send_mail=(bool(params.get('--send_mail', False))))
  else:
    show_help_and_exit()


if '__main__' == __name__:
  main()